"""Durable collection jobs and explicit, paid-model guide requests."""
import asyncio
import copy
import fcntl
import re
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo
from copilot.core import encoded,digest,fail,now,Problem
from copilot.generation import config,availability
from copilot.ai_config import generation_config
from .store import TABLE,preferences,basic_guide
from .sources import CLASSICS,fetch_feed,identify,choose,fetch_article_content

class Reader:
    def __init__(self,store,fetcher=None,transport=None):
        self.store=store;self.fetcher=fetcher or fetch_feed;self.transport=transport;self.tasks={};self.scheduler=None
    @contextmanager
    def gate(self):
        if getattr(self.store,'remote',False):
            with self.store.generation_gate():yield
        else:
            with (self.store.runtime.parent/'.ai-generation.lock').open('a') as stream:
                try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:fail('busy','其他AI任务正在进行，请稍后再试。')
                yield
    def begin(self,data,daily=False):
        data = dict(data)
        credentials = data.pop('ai_config', None)
        kind = data.get('kind', 'collect')
        cfg = generation_config(credentials, self.transport) if kind in ('guide', 'summary', 'english') else config()
        key=data.get('key')
        if not isinstance(key,str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,100}',key):fail('invalid','请求编号无效。',422)
        kind=data.get('kind','collect')
        if kind not in ('collect','guide','summary','english','fetch_full'):fail('invalid','任务类型无效。',422)
        request=digest(encoded(data));jid='job-'+key
        with self.store.lock():
            old=self.store.optional(jid)
            if old:
                if old['request']!=request:fail('conflict','请求编号已用于其他内容。')
                return old
            if any(j['state'] in ('queued','running') for j in self.store.jobs()):fail('busy','已有阅读任务进行中，请等待或取消。')
            p=preferences(data.get('preferences',self.store.prefs()))
            context=None
            if kind=='guide':
                if self.transport is None and availability(self.store):fail('unavailable',availability(self.store),503)
                a=self.store.article(data.get('article_id'))
                if len(a.get('summary',''))<50:fail('invalid','现有摘要太少，无法可靠生成导读，请先阅读原文。',422)
                context={k:a[k] for k in ('id','title','author','source','url','summary','access','language','published_at')}
                context['guide_hash']=a['hashes'][f'认知阅读/文章资料/{a["id"]}/中文导读.md']
            elif kind=='summary':
                if self.transport is None and availability(self.store):fail('unavailable',availability(self.store),503)
                a=self.store.article(data.get('article_id'))
                context={'article_id':a['id']}
            elif kind=='english':
                if self.transport is None and availability(self.store):fail('unavailable',availability(self.store),503)
                a=self.store.article(data.get('article_id'))
                context={'article_id':a['id']}
            elif kind=='fetch_full':
                a=self.store.article(data.get('article_id'))
                context={'article_id':a['id']}
            job={'id':jid,'type':'job','kind':kind,'request':request,'state':'queued','created_at':now(),'date':now()[:10],
                 'daily':daily,'preferences':p,'sources':[],'warnings':[],'candidates':[],'error':None,'context':context,'raw':'','usage':None,'cost':None}
            self.store.put(TABLE,jid,job)
        task=asyncio.create_task(self.run(jid, cfg));self.tasks[jid]=task;task.add_done_callback(lambda _:self.tasks.pop(jid,None));return job
    async def run(self,jid,cfg=None):
        cfg = cfg or config()
        fetch_tasks=[]
        j=self.store.record(jid);j.update(state='running',phase='正在读取来源' if j['kind']=='collect' else '正在准备中文导读');self.store.put(TABLE,jid,j)
        try:
            if j['kind']=='collect':
                candidates=[];p=j['preferences']
                if p['mode']!='classic':
                    all_feeds = self.store.all_sources()
                    selected=[s for s in all_feeds if s['language'] in p['languages'] and set(s['topics'])&set(p['topics'])]
                    async def get(s):
                        try:return s,await self.fetcher(s),None
                        except Exception:return s,[],'读取失败或来源暂不可用'
                    fetch_tasks=[asyncio.create_task(get(s)) for s in selected]
                    for pending in asyncio.as_completed(fetch_tasks):
                        source,items,error=await pending;candidates.extend(items)
                        j['sources'].append({'name':source['name'],'url':source['url'],'count':len(items),'error':error})
                        j['phase']=f'已读取{len(j["sources"])}个来源';self.store.put(TABLE,jid,j)
                if p['mode']!='recent':
                    for classic in CLASSICS:
                        a=copy.deepcopy(classic);a.update(id=identify(a['url']),category='classic');candidates.append(a)
                    j['sources'].append({'name':'已核验经典目录','url':None,'count':len(CLASSICS),'error':None})
                j['candidates']=choose(candidates,p,{a['id'] for a in self.store.articles()},j['date'])
                # Fetch full article content for each candidate
                for a in j['candidates']:
                    j['phase']=f'正在获取原文：{a["title"][:30]}';self.store.put(TABLE,jid,j)
                    content=await fetch_article_content(a['url'])
                    a['full_content']=content or '内容获取失败'
                for a in j['candidates']:a.update(checked_at=now(),heat='热度未核实',reason='符合所选主题；'+('长期阅读价值，经典目录推荐' if a['category']=='classic' else '来自已配置来源、最近30天发表；建议先核对摘要'))
                if len(j['candidates'])<p['count']:j['warnings'].append(f'本次找到{len(j["candidates"])}篇符合条件且未保存的文章，少于目标{p["count"]}篇；没有用旧闻或重复文章凑数。')
                if not j['candidates']:fail('empty','没有符合条件的新文章。可调整主题、语言、类型或稍后重新搜集。')
                j.update(state='ready',phase='搜集完成');self.store.put(TABLE,jid,j)
                if j['daily']:j=self.store.save_selection(jid,[a['id'] for a in j['candidates']])
            elif j['kind']=='summary':
                # Generate comprehensive summary based on full article content
                from copilot.transport import qwen_stream
                c=cfg;j['model']=c['model'];ctx=j['context'];done=False
                a=self.store.article(ctx['article_id'])
                content=a.get('full_content') or a.get('summary','')
                prompt=[{'role':'system','content':'你是一个深度阅读助手。基于文章全文生成一份详细的中文总结报告。'},
                        {'role':'user','content':encoded({'title':a['title'],'author':a.get('author',''),'source':a.get('source',''),'content':content[:12000],'instruction':'请生成包含以下部分的详细总结：\n1. 核心观点（3-5个要点，每个要点用一句话概括）\n2. 关键论据和例子（列举文章中的重要证据、数据或案例，每个论据简要说明）\n3. 作者的主要论证逻辑（作者如何从论据推导出观点？逻辑链条是什么？）\n4. 文章的局限或待讨论之处（有哪些假设未验证？有哪些反面观点未讨论？）\n5. 对读者的启发（2-3点实际帮助或思考方向）'})}]
                with self.gate():
                    async for packet in (self.transport or qwen_stream)(prompt,c):
                        j['raw']+=packet.get('text','')
                        if len(j['raw'])>15000:fail('invalid','总结超出长度限制。')
                        if packet.get('usage'):j['usage']=packet['usage']
                        if packet.get('done'):done=True
                        j['phase']='正在生成详细总结';self.store.put(TABLE,jid,j)
                if not done or not j['raw'].strip():fail('incomplete','总结未完整返回。')
                self.store.save_summary(ctx['article_id'],j['raw']);j.update(state='ready',phase='详细总结已保存',article_id=ctx['article_id'])
            elif j['kind']=='english':
                # Generate English learning material (grammar + vocabulary)
                from copilot.transport import qwen_stream
                c=cfg;j['model']=c['model'];ctx=j['context'];done=False
                a=self.store.article(ctx['article_id'])
                content=a.get('full_content') or a.get('summary','')
                prompt=[{'role':'system','content':'你是一位英语教师。基于这篇英文文章，提取对英语学习者有价值的语法和词汇内容。'},
                        {'role':'user','content':encoded({'title':a['title'],'content':content[:12000],'instruction':'请生成英语学习材料，包含：1. 重点词汇（8-12个高级词汇，含音标、中文释义、原文例句）2. 重要短语和搭配（5-8个）3. 关键语法点（2-3个复杂句式解析，含中文翻译）4. 长难句分析（挑选2-3个典型句子，逐层解析结构）'})}]
                with self.gate():
                    async for packet in (self.transport or qwen_stream)(prompt,c):
                        j['raw']+=packet.get('text','')
                        if len(j['raw'])>15000:fail('invalid','英语学习材料超出长度限制。')
                        if packet.get('usage'):j['usage']=packet['usage']
                        if packet.get('done'):done=True
                        j['phase']='正在生成英语学习材料';self.store.put(TABLE,jid,j)
                if not done or not j['raw'].strip():fail('incomplete','英语学习材料未完整返回。')
                self.store.save_english_learning(ctx['article_id'],j['raw']);j.update(state='ready',phase='英语学习材料已保存',article_id=ctx['article_id'])
            elif j['kind']=='fetch_full':
                # Fetch and save full article content
                a=self.store.article(j['context']['article_id'])
                ctx=j['context']
                j['phase']='正在获取文章原文';self.store.put(TABLE,jid,j)
                content=await fetch_article_content(a['url'])
                if not content or len(content)<100:
                    fail('incomplete','文章内容获取失败或内容过短。')
                # Save to local file
                self.store.save_full_text(ctx['article_id'],content)
                j.update(state='ready',phase='文章已保存',article_id=ctx['article_id'])
            else:
                from copilot.transport import qwen_stream
                c=cfg;j['model']=c['model'];ctx=j['context'];done=False
                a=self.store.article(ctx['id'])
                # Use full content if available, otherwise fall back to summary
                content=a.get('full_content') or a.get('summary','')
                # More comprehensive guide with personal insights
                prompt=[{'role':'system','content':'你是一位深度阅读助手和思考伙伴。基于文章内容生成一份详细的中文导读和解读报告。'},
                        {'role':'user','content':encoded({'title':a['title'],'author':a.get('author',''),'source':a.get('source',''),'content':content[:12000],
                                    'instruction':'请生成包含以下部分的详细导读：\n1. 文章概览（100字简介）\n2. 核心观点（3-5个要点，每个要点展开说明）\n3. 关键论据和例子（列举文章中的重要证据、数据或案例）\n4. 论证逻辑分析（作者如何论证？逻辑链条是什么？）\n5. 批判性思考（文章的局限、可能的反驳、未讨论的方面）\n6. 实用启发（对读者有什么实际帮助？如何应用到生活中？）\n7. 延伸阅读建议（可以进一步探索的相关主题或问题）'})}]
                with self.gate():
                    async for packet in (self.transport or qwen_stream)(prompt,c):
                        j['raw']+=packet.get('text','')
                        if len(j['raw'])>15000:fail('invalid','导读超出长度限制。')
                        if packet.get('usage'):j['usage']=packet['usage']
                        if packet.get('done'):done=True
                        j['phase']='正在生成详细导读';self.store.put(TABLE,jid,j)
                if not done or not j['raw'].strip():fail('incomplete','导读未完整返回，原资料保留。')
                if '<script' in j['raw'].lower() or re.search(r'https?://',j['raw']):fail('invalid','导读含未经核验的链接或脚本，原资料保留。')
                # Format as comprehensive guide
                guide=f'# {a.get("zh_title") or a["title"]} - 详细导读\n\n## 文章信息\n\n- **原标题**：{a["title"]}\n- **作者**：{a.get("author","未知")}\n- **来源**：{a.get("source","未知")}\n- **发表时间**：{a.get("published_at","未知")}\n- **原文链接**：{a["url"]}\n\n---\n\n{j["raw"]}\n\n---\n\n> 本导读由AI基于文章{"全文" if a.get("full_content") else "摘要"}生成，仅供参考。建议阅读原文获取完整信息。\n'
                self.store.save_guide(ctx['id'],guide,ctx['guide_hash']);j.update(state='ready',phase='详细导读已保存',article_id=ctx['id'])
        except asyncio.CancelledError:j.update(state='cancelled',error='任务已取消，已有资料和笔记保留。')
        except Exception as e:j.update(state='failed',error=e.message if isinstance(e,Problem) else '搜集或生成未完成，请检查网络后重试；已有资料保留。')
        finally:
            for task in fetch_tasks:
                if not task.done():task.cancel()
            if fetch_tasks:await asyncio.gather(*fetch_tasks,return_exceptions=True)
            if j.get('usage') and j['kind']=='guide':
                try:
                    c=cfg
                    if c['price_version'] and c['input_price'] and c['output_price']:
                        rates=[float(c['input_price']),float(c['output_price'])]
                        if min(rates)>=0:j['cost']=(j['usage']['prompt_tokens']*rates[0]+j['usage']['completion_tokens']*rates[1])/1000000
                except (KeyError,ValueError,TypeError):pass
            j['finished_at']=now();self.store.put(TABLE,jid,j)
    def cancel(self,jid):
        j=self.store.record(jid)
        if j.get('type')!='job':fail('not_found','阅读任务不存在。',404)
        if j['state'] in ('queued','running'):
            task=self.tasks.get(jid)
            if task:task.cancel()
            j.update(state='cancelled',error='已请求取消。',finished_at=now());self.store.put(TABLE,jid,j)
        return j
    def daily_tick(self,current=None):
        p=self.store.prefs();dt=current or datetime.now(ZoneInfo('Asia/Shanghai'))
        if not p['enabled'] or (dt.hour,dt.minute)<(p['hour'],p['minute']):return None
        key='daily-'+dt.date().isoformat()
        if self.store.optional('job-'+key):return None
        if any(j['state'] in ('queued','running') for j in self.store.jobs()):return None
        return self.begin({'key':key,'preferences':p},daily=True)
    async def schedule(self):
        while True:
            try:self.daily_tick()
            except Exception:pass  # A later tick retries startup/network scheduling, never completed jobs.
            await asyncio.sleep(30)
    async def shutdown(self):
        tasks=list(self.tasks.values())+([self.scheduler] if self.scheduler else [])
        for t in tasks:t.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)

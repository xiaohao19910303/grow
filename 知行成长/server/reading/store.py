"""Local reading records and recoverable exports, using the platform writer lock."""
import copy
import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from copilot.core import digest, encoded, fail, now
from plans.store import Plans, integer
from .sources import TOPICS, DEFAULT_FEEDS

DEFAULT={'enabled':True,'hour':10,'minute':0,'count':3,'mode':'mixed','topics':list(TOPICS),'languages':['zh','en'],'query':''}
TABLE='reading_records'

def preferences(data):
    if not isinstance(data,dict):fail('invalid','阅读偏好格式无效。',422)
    p={**DEFAULT,**data}
    if set(p)!=set(DEFAULT) or type(p['enabled']) is not bool:fail('invalid','阅读偏好字段无效。',422)
    for k,lo,hi in [('hour',0,23),('minute',0,59),('count',1,8)]:integer(p[k],lo,hi,k)
    if p['mode'] not in ('recent','classic','mixed'):fail('invalid','文章类型无效。',422)
    for k,allowed in [('topics',TOPICS),('languages',('zh','en'))]:
        if not isinstance(p[k],list) or not p[k] or any(not isinstance(x,str) or x not in allowed for x in p[k]):fail('invalid','请选择主题与语言。',422)
        p[k]=list(dict.fromkeys(p[k]))
    if not isinstance(p['query'],str) or len(p['query'])>300:fail('invalid','检索词过长。',422)
    return p

class ReadingStore(Plans):
    def path(self,relative):
        if not isinstance(relative,str) or not relative.startswith('认知阅读/') or '..' in Path(relative).parts:fail('invalid','阅读文件路径无效。',422)
        p=self.root/relative
        for part in (p,*p.parents):
            if part.is_symlink():fail('conflict','阅读路径不能经过符号链接。')
            if part==self.root:break
        if not p.resolve().is_relative_to(self.root.resolve()):fail('invalid','阅读路径越界。',422)
        return p
    def initialize(self):
        with self.lock():
            with self.conn() as c:installed=c.execute("SELECT 1 FROM sqlite_master WHERE name='reading_records'").fetchone()
            if not installed:
                from plans.backup import database_snapshot
                database_snapshot(self,self.runtime/('before-reading-'+uuid.uuid4().hex+'.db'))
            with self.conn() as c:c.execute('CREATE TABLE IF NOT EXISTS reading_records (id TEXT PRIMARY KEY,data TEXT NOT NULL)')
            self.recover_exports()
            for job in self.jobs():
                if job['state'] in ('queued','running'):
                    job.update(state='failed',error='服务重启导致任务中断，未自动重试。',finished_at=now());self.put(TABLE,job['id'],job)
            if self.optional('preferences') is None:self.set_preferences_locked(DEFAULT)
    def optional(self,key):
        with self.conn() as c:r=c.execute('SELECT data FROM reading_records WHERE id=?',(key,)).fetchone()
        return json.loads(r[0]) if r else None
    def record(self,key):return self.get(TABLE,key)
    def prefs(self):return self.record('preferences')['value']
    def jobs(self):return [r for r in self.rows(TABLE) if r.get('type')=='job']
    def articles(self):return [r for r in self.rows(TABLE) if r.get('type')=='article']
    def custom_sources(self):
        """获取所有自定义来源"""
        record = self.optional('custom_sources')
        return record['value'] if record else []
    def all_sources(self):
        """获取所有来源（默认+自定义）"""
        custom = self.custom_sources()
        return DEFAULT_FEEDS + custom
    def add_custom_source(self, source_data):
        """添加自定义来源"""
        if not isinstance(source_data, dict):
            fail('invalid', '来源格式无效。', 422)
        # 验证必填字段
        required = ['name', 'url', 'language', 'topics']
        for field in required:
            if field not in source_data or not source_data[field]:
                fail('invalid', f'缺少必填字段：{field}', 422)
        # 验证语言
        if source_data['language'] not in ('zh', 'en'):
            fail('invalid', '语言只能是 zh 或 en', 422)
        # 验证主题
        if not isinstance(source_data['topics'], list) or not source_data['topics']:
            fail('invalid', '至少选择一个主题', 422)
        for topic in source_data['topics']:
            if topic not in TOPICS:
                fail('invalid', f'未知主题：{topic}', 422)
        # 提取域名
        from urllib.parse import urlsplit
        try:
            parsed = urlsplit(source_data['url'])
            if parsed.scheme not in ('http', 'https'):
                fail('invalid', 'URL 必须是 http 或 https', 422)
            domain = parsed.hostname
            if not domain:
                fail('invalid', 'URL 格式无效', 422)
        except Exception:
            fail('invalid', 'URL 格式无效', 422)
        # 创建来源对象
        custom = self.custom_sources()
        source_id = 'custom-' + str(uuid.uuid4())[:8]
        new_source = {
            'id': source_id,
            'name': source_data['name'],
            'url': source_data['url'],
            'language': source_data['language'],
            'domains': [domain],
            'topics': source_data['topics'],
            'custom': True
        }
        custom.append(new_source)
        # 保存
        self.put(TABLE, 'custom_sources', {
            'id': 'custom_sources',
            'type': 'custom_sources',
            'value': custom
        })
        return new_source
    def remove_custom_source(self, source_id):
        """删除自定义来源"""
        if not source_id.startswith('custom-'):
            fail('invalid', '只能删除自定义来源', 422)
        custom = self.custom_sources()
        custom = [s for s in custom if s['id'] != source_id]
        self.put(TABLE, 'custom_sources', {
            'id': 'custom_sources',
            'type': 'custom_sources',
            'value': custom
        })
        return {'removed': source_id}
    def recover_exports(self):
        for r in self.rows(TABLE):
            if r.get('type')=='export' and r['state']=='pending':self.finish_export(r)
    def finish_export(self,journal):
        for rel,change in journal['files'].items():
            if self.hash(rel) not in (change['before'],digest(change['text'])):fail('conflict','阅读文件有外部修改，请先核对：'+rel)
        for rel,change in journal['files'].items():
            if self.hash(rel)==digest(change['text']):continue
            target=self.path(rel);target.parent.mkdir(parents=True,exist_ok=True)
            fd,tmp=tempfile.mkstemp(dir=target.parent,prefix='.reading-')
            try:
                with os.fdopen(fd,'w') as f:f.write(change['text']);f.flush();os.fsync(f.fileno())
                os.replace(tmp,target)
            finally:
                if os.path.exists(tmp):os.unlink(tmp)
        with self.conn() as c:
            for record in journal['records']:
                c.execute('INSERT INTO reading_records VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',(record['id'],encoded(record)))
            journal['state']='done';c.execute('UPDATE reading_records SET data=? WHERE id=?',(encoded(journal),journal['id']))
    def export(self,files,records,expected=None):
        self.recover_exports()
        for rel,h in (expected or {}).items():
            if self.hash(rel)!=h:fail('conflict','文件已被外部修改，请重新读取后核对：'+rel)
        j={'id':'export-'+uuid.uuid4().hex,'type':'export','state':'pending','files':{rel:{'before':self.hash(rel),'text':value} for rel,value in files.items()},'records':records}
        self.put(TABLE,j['id'],j);self.finish_export(j)
    def set_preferences_locked(self,value):
        p=preferences(value);old=self.optional('preferences');rel='认知阅读/阅读偏好.md'
        md='# 阅读偏好\n\n北京时间每天 %02d:%02d；%s；每次%d篇。\n\n主题：%s\n\n语言：%s\n\n本地服务需保持运行；停止后不补历史日期。每日任务不自动调用付费模型。\n'%(p['hour'],p['minute'],'已启用' if p['enabled'] else '已暂停',p['count'],'、'.join(p['topics']),'、'.join(p['languages']))
        files={rel:md}
        readme='认知阅读/README.md'
        if not self.path(readme).exists():files[readme]='# 认知阅读\n\n[阅读偏好](阅读偏好.md)\n\n每日精选按年月归档；文章资料按稳定编号保存；阅读笔记独立存放。\n\n文章来源于已配置订阅及经典目录，不代表全网检索。未核验热度，不标热门；摘要不等于全文。已推荐不等于已读。\n'
        self.export(files,[{'id':'preferences','type':'preferences','value':p,'hash':digest(md)}],{rel:old['hash']} if old else None)
        return p
    def save_preferences(self,data):
        with self.lock():return self.set_preferences_locked(data)
    def note(self,aid):
        self.article(aid);rel=f'认知阅读/阅读笔记/{aid}.md';p=self.path(rel)
        return {'text':p.read_text() if p.exists() else '', 'hash':self.hash(rel)}
    def article(self,aid):
        if not isinstance(aid,str) or not re.fullmatch(r'article-[a-f0-9]{20}',aid):fail('invalid','文章编号无效。',422)
        a=self.record(aid)
        if a.get('type')!='article':fail('invalid','不是文章记录。',422)
        return a
    def update_personal(self,aid,data):
        with self.lock():
            self.recover_exports();a=self.article(aid);files={};expected={}
            for k in ('bookmarked','read_later','read'):
                if k in data:
                    if type(data[k]) is not bool:fail('invalid','阅读状态无效。',422)
                    a[k]=data[k]
            if 'note' in data:
                if not isinstance(data['note'],str) or len(data['note'])>40000:fail('invalid','笔记过长。',422)
                rel=f'认知阅读/阅读笔记/{aid}.md';files[rel]=data['note'];expected[rel]=data.get('note_hash')
            rel=f'认知阅读/文章资料/{aid}/文章信息.json';expected[rel]=a['hashes'][rel]
            mirror={k:v for k,v in a.items() if k not in ('hashes','guide')};files[rel]=encoded(mirror)
            a['hashes'].update({r:digest(v) for r,v in files.items() if '/阅读笔记/' not in r})
            self.export(files,[a],expected)
            return {**a,**({'note_hash':digest(data['note'])} if 'note' in data else {})}
    def save_selection(self,jid,ids):
        with self.lock():
            self.recover_exports();job=self.record(jid)
            if job.get('kind')!='collect' or job['state']!='ready':fail('conflict','搜集结果尚未就绪。')
            if not isinstance(ids,list) or not ids or any(not isinstance(x,str) for x in ids):fail('invalid','请选择文章。',422)
            ids=list(dict.fromkeys(ids));lookup={a['id']:a for a in job['candidates']}
            if not set(ids)<=lookup.keys():fail('invalid','包含本次结果之外的文章。',422)
            if job.get('saved_ids'):
                if set(ids)!=set(job['saved_ids']):fail('conflict','本次结果已保存，请重新搜集。')
                return job
            records=[];files={};expected={};date=job['date']
            for aid in ids:
                if self.optional(aid):continue
                a=copy.deepcopy(lookup[aid]);a.update(type='article',saved_at=now(),bookmarked=False,read_later=False,read=False)
                a['guide']=basic_guide(a);base=f'认知阅读/文章资料/{aid}'
                files[base+'/文章信息.json']=encoded({k:v for k,v in a.items() if k not in ('guide','full_content')})
                files[base+'/中文导读.md']=a['guide']
                # Save full article content if available
                if a.get('full_content'):
                    files[base+'/原文.md']=f'# {a["title"]}\n\n{a["full_content"]}'
                for rel in (base+'/文章信息.json',base+'/中文导读.md',base+'/原文.md'):
                    if rel in files:expected[rel]=None
                a['hashes']={rel:digest(files[rel]) for rel in files if rel in (base+'/文章信息.json',base+'/中文导读.md',base+'/原文.md')};records.append(a)
            label='今日精选' if job.get('daily') else '搜集-'+jid
            index=f'认知阅读/每日精选/{date[:4]}/{date[5:7]}/{date}-{label}.md'
            lines=[f'# {date} {label}','',f'实际保存{len(ids)}篇；热度未核实。','']
            for aid in ids:
                a=lookup[aid];lines += [f'## {a.get("zh_title") or a["title"]}',f'[{a["title"]}]({a["url"]})',f'[本地导读](../../../文章资料/{aid}/中文导读.md)','']
            files[index]='\n'.join(lines);expected[index]=None
            log=f'认知阅读/搜集记录/{date}-{jid}.md';files[log]='# 搜集记录\n\n'+encoded({k:job[k] for k in ('date','preferences','sources','warnings')})+'\n';expected[log]=None
            job.update(saved_ids=ids,saved_at=now(),path=str(self.path(index)));records.append(job)
            self.export(files,records,expected);return job
    def save_guide(self,aid,guide,expected_hash):
        with self.lock():
            self.recover_exports();a=self.article(aid);rel=f'认知阅读/文章资料/{aid}/中文导读.md'
            if a['hashes'][rel]!=expected_hash:fail('conflict','导读已经更新，请先查看新版。')
            a['guide']=guide;a['hashes'][rel]=digest(guide)
            self.export({rel:guide},[a],{rel:expected_hash});return a
    def save_summary(self,aid,summary):
        """Save comprehensive AI summary based on full article content."""
        with self.lock():
            self.recover_exports();a=self.article(aid);rel=f'认知阅读/文章资料/{aid}/详细总结.md'
            content=f'# {a["title"]} - 详细总结\n\n{summary}\n'
            expected={rel:a['hashes'].get(rel)}
            a['hashes'][rel]=digest(content)
            self.export({rel:content},[a],expected);return a
    def save_english_learning(self,aid,content):
        """Save English learning material (vocabulary, grammar, sentence analysis)."""
        with self.lock():
            self.recover_exports();a=self.article(aid);rel=f'认知阅读/文章资料/{aid}/英语学习.md'
            full_content=f'# {a["title"]} - 英语学习材料\n\n{content}\n'
            expected={rel:a['hashes'].get(rel)}
            a['hashes'][rel]=digest(full_content)
            self.export({rel:full_content},[a],expected);return a
    def save_full_text(self,aid,content):
        """Save full article text to local file."""
        with self.lock():
            self.recover_exports();a=self.article(aid);rel=f'认知阅读/文章资料/{aid}/原文.md'
            # Clean up content and format as markdown
            # Remove excessive whitespace
            content = re.sub(r'\n{3,}', '\n\n', content)
            content = re.sub(r' {2,}', ' ', content)
            full_content=f'# {a.get("zh_title") or a["title"]}\n\n> 原标题：{a["title"]}\n> 作者：{a.get("author","未知")} | 来源：{a.get("source","未知")} | 发表：{a.get("published_at","未知")}\n> 原文链接：{a["url"]}\n\n---\n\n{content}\n'
            expected={rel:a['hashes'].get(rel)}
            a['hashes'][rel]=digest(full_content)
            # Also save to full_content field in article record
            a['full_content']=content
            self.export({rel:full_content},[a],expected);return a

def basic_guide(a):
    return (f'# {a.get("zh_title") or a["title"]}\n\n原标题：{a["title"]}\n\n作者：{a["author"]}｜来源：{a["source"]}｜发表：{a.get("published_at") or "未知"}\n\n'
            f'[阅读原文]({a["url"]})\n\n## 阅读范围\n{a["access"]}。热度未核实。\n\n'
            f'## 已有摘要（保持来源语言）\n{a["summary"] or "来源未提供摘要，请打开原文阅读。"}\n\n'
            '## 阅读提示\n先找作者的核心主张，再区分证据、解释与观点。记录一个支持例子和一个可能不适用的情境。\n\n'
            '## 思考问题\n这篇文章提供了什么新证据？它改变了我的哪个假设？哪些结论需要进一步核验？\n\n'
            '## 边界\n摘要不能替代原文。平台尚未生成文章专属AI中文导读；可在页面显式请求，个人笔记不会发送。\n')

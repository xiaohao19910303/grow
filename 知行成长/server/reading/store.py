"""Local reading records and recoverable exports, using the platform writer lock."""
import copy
import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from copilot.core import digest, encoded, fail, now
from plans.store import Plans, integer
from .sources import TOPICS, DEFAULT_FEEDS, identify

DEFAULT={'enabled':True,'hour':10,'minute':0,'count':3,'mode':'mixed','topics':list(TOPICS),'languages':['zh','en'],'query':'','auto_guide':False}
TABLE='reading_records'

def preferences(data):
    if not isinstance(data,dict):fail('invalid','阅读偏好格式无效。',422)
    p={**DEFAULT,**data}
    if set(p)!=set(DEFAULT) or any(type(p[k]) is not bool for k in ('enabled','auto_guide')):fail('invalid','阅读偏好字段无效。',422)
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
        if os.getenv('PLAN_CONTENT_BACKEND') == 'github':
            fail('legacy_content_migration', '旧认知阅读的文件与笔记尚未完成云端迁移，暂不写入临时磁盘。', 503)
        with self.lock():
            with self.conn() as c:installed=c.execute("SELECT 1 FROM sqlite_master WHERE name='reading_records'").fetchone()
            if not installed:
                from plans.backup import database_snapshot
                database_snapshot(self,self.runtime/('before-reading-'+uuid.uuid4().hex+'.db'))
            with self.conn() as c:c.execute('CREATE TABLE IF NOT EXISTS reading_records (id TEXT PRIMARY KEY,data TEXT NOT NULL)')
            # Phase 2: vocabulary and review tables
            with self.conn() as c:
                c.execute('''CREATE TABLE IF NOT EXISTS reading_vocabulary (
                    id TEXT PRIMARY KEY, word TEXT NOT NULL, normalized TEXT NOT NULL,
                    article_id TEXT, source_version INTEGER DEFAULT 1,
                    context_sentence TEXT, contextual_meaning TEXT,
                    part_of_speech TEXT, pronunciation TEXT,
                    step INTEGER DEFAULT 0, next_review TEXT,
                    paused INTEGER DEFAULT 0, archived INTEGER DEFAULT 0,
                    created_at TEXT, updated_at TEXT, data TEXT NOT NULL DEFAULT '{}')''')
                c.execute('CREATE INDEX IF NOT EXISTS idx_vocab_word ON reading_vocabulary(normalized)')
                c.execute('CREATE INDEX IF NOT EXISTS idx_vocab_review ON reading_vocabulary(next_review) WHERE paused=0 AND archived=0')
                c.execute('''CREATE TABLE IF NOT EXISTS reading_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vocab_id TEXT NOT NULL, feedback TEXT NOT NULL,
                    step_before INTEGER, step_after INTEGER,
                    reviewed_at TEXT,
                    FOREIGN KEY (vocab_id) REFERENCES reading_vocabulary(id))''')
                c.execute('CREATE INDEX IF NOT EXISTS idx_review_vocab ON reading_reviews(vocab_id)')
            self.recover_exports()
            self.restore_article_index()
            for job in self.jobs():
                if job['state'] in ('queued','running'):
                    job.update(state='failed',error='服务重启导致任务中断，未自动重试。',finished_at=now());self.put(TABLE,job['id'],job)
            if self.optional('preferences') is None:self.set_preferences_locked(DEFAULT)
    def restore_article_index(self):
        """Reattach local mirrors missing from the index; never replace indexed records or files.

        Called under the writer lock after pending exports have recovered.
        """
        records=[]
        base=self.path('认知阅读/文章资料')
        if not base.is_dir():return 0
        for metadata in sorted(base.glob('article-*/文章信息.json')):
            aid=metadata.parent.name
            if not re.fullmatch(r'article-[a-f0-9]{20}',aid) or self.optional(aid):continue
            rel=f'认知阅读/文章资料/{aid}'
            try:
                a=json.loads(self.path(rel+'/文章信息.json').read_text(encoding='utf-8'))
                if not isinstance(a,dict) or a.get('id')!=aid or a.get('type')!='article':continue
                if any(not isinstance(a.get(k),str) or not a[k] for k in ('title','url','source','saved_at')):continue
                url=urlsplit(a['url'])
                if url.scheme not in ('http','https') or not url.hostname or url.username or url.password:continue
                if identify(a['url'])!=aid or a.get('language') not in ('zh','en'):continue
                if any(k in a and type(a[k]) is not bool for k in ('read','read_later','bookmarked','archived')):continue
                hashes={};contents={}
                for name in ('文章信息.json','中文导读.md','原文.md','详细总结.md','英语学习.md'):
                    path=rel+'/'+name;file=self.path(path)
                    if file.is_file():
                        raw=file.read_bytes();hashes[path]=digest(raw);contents[name]=raw.decode('utf-8')
                a.update(hashes=hashes,guide=contents.get('中文导读.md',''))
                if '原文.md' in contents and not a.get('full_content'):a['full_content']=contents['原文.md']
                for key in ('read','read_later','bookmarked'):a.setdefault(key,False)
                a.setdefault('access','从本地已保存资料恢复；未重新核验原文')
                records.append(a)
            except (OSError,ValueError,UnicodeError):
                continue
        with self.conn() as c:
            for a in records:
                c.execute('INSERT INTO reading_records VALUES (?,?) ON CONFLICT(id) DO NOTHING',(a['id'],encoded(a)))
        return len(records)
    def optional(self,key):
        with self.conn() as c:r=c.execute('SELECT data FROM reading_records WHERE id=?',(key,)).fetchone()
        return json.loads(r[0]) if r else None
    def record(self,key):return self.get(TABLE,key)
    def prefs(self):return {**DEFAULT,**self.record('preferences')['value']}
    def jobs(self):return [r for r in self.rows(TABLE) if r.get('type')=='job']
    def articles(self,search=None,include_archived=False):
        """获取文章列表，支持搜索和归档过滤。"""
        result=[]
        for r in self.rows(TABLE):
            if r.get('type')!='article':continue
            if not include_archived and r.get('archived'):continue
            if search:
                q=search.lower()
                feedback=r.get('feedback') or {}
                hay=' '.join(str(r.get(f,'')) for f in ('title','zh_title','author','source','summary','guide','full_content'))
                hay+=' '+' '.join(str(feedback.get(f,'')) for f in ('takeaway','question','action'))
                hay+=' '+' '.join(r.get('tags',[])+feedback.get('tags',[]))
                if q not in hay.lower():continue
            result.append(r)
        return result
    def search_articles(self,query,include_archived=False):
        """按标题/作者/来源/标签搜索文章。"""
        return self.articles(search=query,include_archived=include_archived)
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
    def save_feedback(self,aid,data):
        if not isinstance(data,dict) or set(data)-{'version','value','difficulty','takeaway','question','action','tags','mark_read'}:
            fail('invalid','阅读反馈字段无效。',422)
        version=integer(data.get('version'),0,2147483647,'反馈版本')
        result={}
        for key,allowed in [('value',('','insightful','neutral','not_for_me')),('difficulty',('','easy','right','hard'))]:
            if data.get(key,'') not in allowed:fail('invalid','请选择有效的价值和难度反馈。',422)
            result[key]=data.get(key,'')
        for key,limit in [('takeaway',4000),('question',2000),('action',2000)]:
            value=data.get(key,'')
            if not isinstance(value,str) or len(value)>limit:fail('invalid','反馈内容过长或格式无效。',422)
            result[key]=value.strip()
        tags=data.get('tags',[])
        if not isinstance(tags,list) or len(tags)>8 or any(not isinstance(t,str) or not t.strip() or len(t)>32 for t in tags):
            fail('invalid','最多填写 8 个标签，每个标签不超过 32 字。',422)
        if type(data.get('mark_read',False)) is not bool:fail('invalid','读完状态无效。',422)
        result.update(tags=list(dict.fromkeys(t.strip() for t in tags)),version=version+1,updated_at=now())
        with self.lock():
            self.recover_exports();a=self.article(aid)
            if a.get('feedback',{}).get('version',0)!=version:fail('conflict','反馈已在其他页面更新，请保留输入并重新核对。')
            a['feedback']=result
            if data.get('mark_read'):a['read']=True
            a['record_version']=a.get('record_version',1)+1
            return self._persist_article_info(a)
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
    def save_guide(self,aid,guide,expected_hash,details=None):
        with self.lock():
            self.recover_exports();a=self.article(aid);rel=f'认知阅读/文章资料/{aid}/中文导读.md'
            if a['hashes'][rel]!=expected_hash:fail('conflict','导读已经更新，请先查看新版。')
            a['guide']=guide;a['hashes'][rel]=digest(guide)
            files={rel:guide};expected={rel:expected_hash}
            if details:
                a.update(details)
                info=f'认知阅读/文章资料/{aid}/文章信息.json'
                expected[info]=a['hashes'].get(info)
                files[info]=encoded({k:v for k,v in a.items() if k not in ('hashes','guide')})
                a['hashes'][info]=digest(files[info])
            self.export(files,[a],expected);return a
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
            a['content_version']=2
            a['content_saved_at']=now()
            self.export({rel:full_content},[a],expected);return a
    def archive_article(self,aid):
        """归档文章（不删除，可恢复）。"""
        with self.lock():
            self.recover_exports();a=self.article(aid)
            if a.get('archived'):return a
            a['archived']=True;a['record_version']=a.get('record_version',1)+1
            rel=f'认知阅读/文章资料/{aid}/文章信息.json'
            expected={rel:a['hashes'].get(rel)}
            mirror={k:v for k,v in a.items() if k not in ('hashes','guide')}
            files={rel:encoded(mirror)}
            a['hashes'][rel]=digest(files[rel])
            self.export(files,[a],expected);return a
    def restore_article(self,aid):
        """恢复已归档文章。"""
        with self.lock():
            self.recover_exports();a=self.article(aid)
            if not a.get('archived'):return a
            a['archived']=False;a['record_version']=a.get('record_version',1)+1
            rel=f'认知阅读/文章资料/{aid}/文章信息.json'
            expected={rel:a['hashes'].get(rel)}
            mirror={k:v for k,v in a.items() if k not in ('hashes','guide')}
            files={rel:encoded(mirror)}
            a['hashes'][rel]=digest(files[rel])
            self.export(files,[a],expected);return a
    def import_from_url(self,url,content,title=None,author=None,language='zh',tags=None):
        """从 URL 导入文章（正文已抓取）。"""
        from .sources import identify
        with self.lock():
            self.recover_exports()
            aid=identify(url)
            if self.optional(aid):
                fail('conflict','该链接已收藏。',409)
            if not title or not title.strip():
                fail('invalid','请填写标题。',422)
            if not content or not content.strip():
                fail('invalid','未获取到正文。',422)
            content_scope='full' if len(content)>500 else 'partial'
            a={
                'id':aid,'type':'article','url':url,
                'title':title.strip()[:300],
                'zh_title':title.strip()[:300] if language=='zh' else '',
                'author':(author or '未提供').strip()[:200],
                'source':urlsplit(url).hostname or '手动导入',
                'language':language if language in ('zh','en') else 'zh',
                'published_at':now()[:10],
                'summary':content[:500].strip(),
                'full_content':content[:50000],
                'topics':['认知'],
                'access':'手动导入；正文已保存',
                'category':'recent',
                'saved_at':now(),
                'bookmarked':False,'read_later':False,'read':False,
                'archived':False,
                'schema_version':2,
                'content_scope':content_scope,
                'source_version':1,
                'record_version':1,
                'import_method':'url',
                'tags':tags or [],
            }
            a['guide']=basic_guide(a)
            base=f'认知阅读/文章资料/{aid}'
            files={}
            files[base+'/文章信息.json']=encoded({k:v for k,v in a.items() if k not in ('guide','full_content')})
            files[base+'/中文导读.md']=a['guide']
            files[base+'/原文.md']=f'# {a["title"]}\n\n{content}'
            for rel in files:
                (self.path(rel)).parent.mkdir(parents=True,exist_ok=True)
            a['hashes']={rel:digest(files[rel]) for rel in files}
            self.export(files,[a],{rel:None for rel in files})
            return a
    def import_from_paste(self,title,content,author=None,language='zh',tags=None,url=None):
        """从粘贴正文导入文章。"""
        from .sources import identify
        with self.lock():
            self.recover_exports()
            effective_url=url or f'paste://{digest(content[:200])[:16]}'
            aid=identify(effective_url)
            if self.optional(aid):
                fail('conflict','该文章已存在。',409)
            if not title or not title.strip():
                fail('invalid','请填写标题。',422)
            if not content or not content.strip():
                fail('invalid','正文不能为空。',422)
            content_scope='full' if len(content)>500 else 'partial'
            a={
                'id':aid,'type':'article','url':effective_url,
                'title':title.strip()[:300],
                'zh_title':title.strip()[:300] if language=='zh' else '',
                'author':(author or '未提供').strip()[:200],
                'source':urlsplit(effective_url).hostname if effective_url.startswith('http') else '手动粘贴',
                'language':language if language in ('zh','en') else 'zh',
                'published_at':now()[:10],
                'summary':content[:500].strip(),
                'full_content':content[:50000],
                'topics':['认知'],
                'access':'手动粘贴导入',
                'category':'recent',
                'saved_at':now(),
                'bookmarked':False,'read_later':False,'read':False,
                'archived':False,
                'schema_version':2,
                'content_scope':content_scope,
                'source_version':1,
                'record_version':1,
                'import_method':'paste',
                'tags':tags or [],
            }
            a['guide']=basic_guide(a)
            base=f'认知阅读/文章资料/{aid}'
            files={}
            files[base+'/文章信息.json']=encoded({k:v for k,v in a.items() if k not in ('guide','full_content')})
            files[base+'/中文导读.md']=a['guide']
            files[base+'/原文.md']=f'# {a["title"]}\n\n{content}'
            for rel in files:
                (self.path(rel)).parent.mkdir(parents=True,exist_ok=True)
            a['hashes']={rel:digest(files[rel]) for rel in files}
            self.export(files,[a],{rel:None for rel in files})
            return a
    # Phase 2: translation drafts, summary/english drafts, vocabulary, review
    REVIEW_INTERVALS=[1,3,7,14,30]
    def _normalize_word(self,word):
        if not isinstance(word,str):fail('invalid','词条必须是字符串。',422)
        n=word.strip().lower()
        if not n:fail('invalid','词条不能为空。',422)
        return n
    def add_vocabulary(self,article_id,word,context_sentence=None,contextual_meaning=None,part_of_speech=None,pronunciation=None,source_version=1):
        normalized=self._normalize_word(word)
        vid='vocab-'+uuid.uuid4().hex[:12]
        now_str=now()
        from datetime import datetime,timedelta
        next_review=(datetime.now()+timedelta(days=1)).strftime('%Y-%m-%d')
        with self.lock():
            with self.conn() as c:
                if c.execute('SELECT id FROM reading_vocabulary WHERE normalized=? AND article_id=?',(normalized,article_id)).fetchone():
                    fail('conflict','该词条已存在。',409)
                c.execute('''INSERT INTO reading_vocabulary
                    (id,word,normalized,article_id,source_version,context_sentence,contextual_meaning,part_of_speech,pronunciation,step,next_review,created_at,updated_at,data)
                    VALUES (?,?,?,?,?,?,?,?,?,0,?,?,?,'{}')''',
                    (vid,word,normalized,article_id,source_version,context_sentence,contextual_meaning,part_of_speech,pronunciation,next_review,now_str,now_str))
        return self.get_vocabulary(vid)
    def get_vocabulary(self,vid):
        with self.conn() as c:
            r=c.execute('''SELECT id,word,normalized,article_id,source_version,context_sentence,contextual_meaning,part_of_speech,pronunciation,step,next_review,paused,archived,created_at,updated_at,data
                FROM reading_vocabulary WHERE id=?''',(vid,)).fetchone()
        if not r:fail('not_found','词条不存在。',404)
        return {'id':r[0],'word':r[1],'normalized':r[2],'article_id':r[3],'source_version':r[4],'context_sentence':r[5],'contextual_meaning':r[6],'part_of_speech':r[7],'pronunciation':r[8],'step':r[9],'next_review':r[10],'paused':bool(r[11]),'archived':bool(r[12]),'created_at':r[13],'updated_at':r[14],'data':json.loads(r[15])}
    def list_vocabulary(self,article_id=None,include_archived=False,include_paused=True):
        q='SELECT id FROM reading_vocabulary WHERE 1=1'
        p=[]
        if article_id:q+=' AND article_id=?';p.append(article_id)
        if not include_archived:q+=' AND archived=0'
        if not include_paused:q+=' AND paused=0'
        q+=' ORDER BY created_at DESC'
        with self.conn() as c:rows=c.execute(q,p).fetchall()
        return [self.get_vocabulary(r[0]) for r in rows]
    def get_due_vocabulary(self,article_id=None):
        today=now()[:10]
        q='SELECT id FROM reading_vocabulary WHERE next_review <= ? AND paused=0 AND archived=0'
        p=[today]
        if article_id:q+=' AND article_id=?';p.append(article_id)
        q+=' ORDER BY next_review ASC'
        with self.conn() as c:rows=c.execute(q,p).fetchall()
        return [self.get_vocabulary(r[0]) for r in rows]
    def review_vocabulary(self,vid,feedback):
        if feedback not in ('again','hard','good'):fail('invalid','反馈类型无效。',422)
        with self.lock():
            v=self.get_vocabulary(vid);old_step=v['step']
            if feedback=='again':new_step=0
            elif feedback=='hard':new_step=old_step
            else:new_step=min(old_step+1,len(self.REVIEW_INTERVALS)-1)
            from datetime import datetime,timedelta
            next_review=(datetime.now()+timedelta(days=self.REVIEW_INTERVALS[new_step])).strftime('%Y-%m-%d')
            now_str=now()
            with self.conn() as c:
                c.execute('INSERT INTO reading_reviews (vocab_id,feedback,step_before,step_after,reviewed_at) VALUES (?,?,?,?,?)',(vid,feedback,old_step,new_step,now_str))
                c.execute('UPDATE reading_vocabulary SET step=?,next_review=?,updated_at=? WHERE id=?',(new_step,next_review,now_str,vid))
        return self.get_vocabulary(vid)
    def pause_vocabulary(self,vid,paused):
        with self.lock():
            with self.conn() as c:c.execute('UPDATE reading_vocabulary SET paused=?,updated_at=? WHERE id=?',(1 if paused else 0,now(),vid))
        return self.get_vocabulary(vid)
    def archive_vocabulary(self,vid,archived):
        with self.lock():
            with self.conn() as c:c.execute('UPDATE reading_vocabulary SET archived=?,updated_at=? WHERE id=?',(1 if archived else 0,now(),vid))
        return self.get_vocabulary(vid)
    def delete_vocabulary(self,vid):
        with self.lock():
            with self.conn() as c:
                c.execute('DELETE FROM reading_reviews WHERE vocab_id=?',(vid,))
                c.execute('DELETE FROM reading_vocabulary WHERE id=?',(vid,))
        return {'deleted':vid}
    def get_vocabulary_stats(self,article_id=None):
        today=now()[:10]
        q='''SELECT COUNT(*),SUM(CASE WHEN paused=0 AND archived=0 THEN 1 ELSE 0 END),SUM(CASE WHEN paused=1 THEN 1 ELSE 0 END),SUM(CASE WHEN archived=1 THEN 1 ELSE 0 END),SUM(CASE WHEN next_review <= ? AND paused=0 AND archived=0 THEN 1 ELSE 0 END) FROM reading_vocabulary WHERE 1=1'''
        p=[today]
        if article_id:q+=' AND article_id=?';p.append(article_id)
        with self.conn() as c:r=c.execute(q,p).fetchone()
        return {'total':r[0] or 0,'active':r[1] or 0,'paused':r[2] or 0,'archived':r[3] or 0,'due':r[4] or 0}
    def _save_draft_field(self,a,field_key,text,version=None):
        existing=a.get(field_key,{})
        new_version=version or (existing.get('version',0)+1)
        a[field_key]={'text':text,'version':new_version,'adopted':False,'created_at':now()}
        a['record_version']=a.get('record_version',1)+1
        return self._persist_article_info(a)
    def _adopt_draft_field(self,a,field_key,file_rel,file_title):
        draft=a.get(field_key)
        if not draft or not draft.get('text'):fail('not_found','无草稿。',404)
        draft['adopted']=True;draft['adopted_at']=now();a[field_key]=draft
        a['record_version']=a.get('record_version',1)+1
        content=f'# {file_title}\n\n{draft["text"]}\n'
        expected={file_rel:a['hashes'].get(file_rel)}
        a['hashes'][file_rel]=digest(content)
        files={file_rel:content}
        info_rel=f'认知阅读/文章资料/{a["id"]}/文章信息.json'
        expected[info_rel]=a['hashes'].get(info_rel)
        mirror={k:v for k,v in a.items() if k not in ('hashes','guide')}
        files[info_rel]=encoded(mirror);a['hashes'][info_rel]=digest(files[info_rel])
        self.export(files,[a],expected);return a
    def _persist_article_info(self,a):
        """Persist article info to file. Caller must hold self.lock()."""
        rel=f'认知阅读/文章资料/{a["id"]}/文章信息.json'
        expected={rel:a['hashes'].get(rel)}
        mirror={k:v for k,v in a.items() if k not in ('hashes','guide')}
        files={rel:encoded(mirror)};a['hashes'][rel]=digest(files[rel])
        self.export(files,[a],expected)
        return a
    def save_translation_draft(self,aid,paragraph_id,translation,version=None):
        with self.lock():
            self.recover_exports();a=self.article(aid)
            drafts=a.get('translation_drafts',{})
            existing=drafts.get(paragraph_id,{})
            new_version=version or (existing.get('version',0)+1)
            drafts[paragraph_id]={'text':translation,'version':new_version,'adopted':False,'created_at':now()}
            a['translation_drafts']=drafts;a['record_version']=a.get('record_version',1)+1
            return self._persist_article_info(a)
    def adopt_translation(self,aid,paragraph_id):
        with self.lock():
            self.recover_exports();a=self.article(aid)
            drafts=a.get('translation_drafts',{})
            if paragraph_id not in drafts:fail('not_found','该段落无翻译草稿。',404)
            drafts[paragraph_id]['adopted']=True;drafts[paragraph_id]['adopted_at']=now()
            a['translation_drafts']=drafts;a['record_version']=a.get('record_version',1)+1
            return self._persist_article_info(a)
    def get_translation_draft(self,aid,paragraph_id=None):
        a=self.article(aid);drafts=a.get('translation_drafts',{})
        return drafts.get(paragraph_id) if paragraph_id else drafts
    def save_summary_draft(self,aid,summary_text,version=None):
        with self.lock():
            self.recover_exports();a=self.article(aid)
            return self._save_draft_field(a,'summary_draft',summary_text,version)
    def adopt_summary(self,aid):
        with self.lock():
            self.recover_exports();a=self.article(aid)
            return self._adopt_draft_field(a,'summary_draft',f'认知阅读/文章资料/{aid}/详细总结.md',f'{a["title"]} - 详细总结')
    def save_english_draft(self,aid,content,version=None):
        with self.lock():
            self.recover_exports();a=self.article(aid)
            return self._save_draft_field(a,'english_draft',content,version)
    def adopt_english(self,aid):
        with self.lock():
            self.recover_exports();a=self.article(aid)
            return self._adopt_draft_field(a,'english_draft',f'认知阅读/文章资料/{aid}/英语学习.md',f'{a["title"]} - 英语学习材料')

def basic_guide(a):
    return (f'# {a.get("zh_title") or a["title"]}\n\n原标题：{a["title"]}\n\n作者：{a["author"]}｜来源：{a["source"]}｜发表：{a.get("published_at") or "未知"}\n\n'
            f'[阅读原文]({a["url"]})\n\n## 阅读范围\n{a["access"]}。热度未核实。\n\n'
            f'## 已有摘要（保持来源语言）\n{a["summary"] or "来源未提供摘要，请打开原文阅读。"}\n\n'
            '## 阅读提示\n先找作者的核心主张，再区分证据、解释与观点。记录一个支持例子和一个可能不适用的情境。\n\n'
            '## 思考问题\n这篇文章提供了什么新证据？它改变了我的哪个假设？哪些结论需要进一步核验？\n\n'
            '## 边界\n摘要不能替代原文。平台尚未生成文章专属AI中文导读；可在页面显式请求，个人笔记不会发送。\n')

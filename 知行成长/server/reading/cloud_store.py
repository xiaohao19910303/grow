"""Reading metadata and notes in PostgreSQL; adopted article documents in GitHub."""
import json
import uuid
from contextlib import contextmanager
from urllib.parse import urlsplit

from cloud_content import Documents, ContentPath, enabled
from copilot.core import digest, encoded, fail, now, Problem
from legacy_schema import migrate
from .store import ReadingStore, TABLE, DEFAULT, preferences
from .sources import identify


def validate_article_source(data,aid):
    if not isinstance(data,dict) or data.get('id')!=aid or data.get('type')!='article':fail('migration_invalid','文章信息与目录编号不一致。')
    for field in ('title','url','source','saved_at'):
        if not isinstance(data.get(field),str) or not data[field]:fail('migration_invalid','文章信息缺少必填字段。')
    try:
        url=urlsplit(data['url'])
        if url.scheme not in ('http','https') or not url.hostname or url.username or url.password or identify(data['url'])!=aid:raise ValueError()
        url.port
    except ValueError:fail('migration_invalid','文章网址或稳定编号无效，来源原文保留。')


class CloudReadingStore(ReadingStore):
    remote=True

    def __init__(self,root,db,content=None):
        super().__init__(root,db)
        self.documents=Documents(self,content)

    def initialize(self):
        migrate()
        self.documents.initialize()
        with self.lock():
            try:self.recover_exports()
            except Problem as exc:
                if exc.code not in ('content_conflict','conflict','github_conflict','github_unavailable','github_access'):raise
            self.restore_article_index(missing_only=True)
            for job in self.jobs():
                if job['state'] in ('queued','running'):
                    job.update(state='failed',error='服务重启导致任务中断，未自动重试。',finished_at=now())
                    self.put(TABLE,job['id'],job)
            if self.optional('preferences') is None:
                self.put(TABLE,'preferences',{'id':'preferences','type':'preferences','value':{**DEFAULT,'enabled':False},'hash':None,'migration_seed':True})

    @contextmanager
    def lock(self):
        with self.documents.lock():yield

    def enqueue_collection(self,job):
        """Admit a collection in one transaction, without downloading job history."""
        with self.conn() as c:
            schema=c.execute('SELECT current_schema()').fetchone()[0]
            # Match Documents.lock so admission still coordinates with other workers.
            for identity in sorted({int(digest(name)[:15],16) for name in ('learning-plan-publications',schema+':learning-plan-publications')}):
                c.execute('SELECT pg_advisory_xact_lock(?)',(identity,))
            # Legacy PDF strings can contain escaped NULs. Normalize only the
            # filter input; the original records are returned and stored intact.
            rows=c.execute("""SELECT id,data FROM reading_records WHERE id=? OR
                (replace(data,?,?)::jsonb->>'type'='job' AND
                 replace(data,?,?)::jsonb->>'state' IN ('queued','running'))""",
                (job['id'],r'\u0000',r'\ufffd',r'\u0000',r'\ufffd')).fetchall()
            existing={row[0]:json.loads(row[1]) for row in rows}
            old=existing.get(job['id'])
            if old:
                if old.get('request')!=job['request']:fail('conflict','请求编号已用于其他内容。')
                return old,False
            if existing:fail('busy','已有阅读任务进行中，请等待或取消。')
            c.execute('INSERT INTO reading_records VALUES (?,?)',(job['id'],encoded(job)))
        return job,True

    def generation_gate(self):return self.documents.generation_gate()

    def article_detail(self,aid):
        """Read one article without repeated metadata connections or job history."""
        a=self.article(aid)
        base=f'认知阅读/文章资料/{aid}'
        guide=base+'/中文导读.md';body=base+'/原文.md';note=f'认知阅读/阅读笔记/{aid}.md'
        paths=[guide,body,note,base+'/详细总结.md',base+'/英语学习.md']
        with self.conn() as c:
            row=c.execute("SELECT data FROM reading_records WHERE id='preferences'").fetchone()
            settings=json.loads(row[0])['value'] if row else DEFAULT
            documents={r[0]:json.loads(r[1]) for r in c.execute(
                'SELECT path,data FROM cloud_documents WHERE path IN (?,?,?,?,?)',paths)}
            jobs=c.execute("""SELECT data FROM reading_records
                WHERE replace(data,?,?)::jsonb->>'type'='job'
                  AND replace(data,?,?)::jsonb->>'kind'='fetch_full'
                  AND replace(data,?,?)::jsonb->'context'->>'article_id'=?
                ORDER BY replace(data,?,?)::jsonb->>'created_at' DESC LIMIT 1""",
                (r'\u0000',r'\ufffd',r'\u0000',r'\ufffd',r'\u0000',r'\ufffd',aid,r'\u0000',r'\ufffd')).fetchall()
        def read_document(path,cached=None):
            item=documents.get(path)
            if item is None:return None
            if cached is not None and digest(cached)==item['hash']:return cached
            text=self.documents.content.read_text(path,item['commit_sha']) if item['storage']=='github' else item['text']
            if digest(text)!=item['hash']:fail('content_hash','内容校验失败，已停止读写。',409)
            return text
        full_text=a.get('full_content')
        if not full_text:full_text=read_document(body)
        latest=json.loads(jobs[0][0]) if jobs else None
        if latest:latest={k:v for k,v in latest.items() if k not in ('context','request')}
        metadata=documents.get(guide)
        return {'article':a,'reading_preferences':preferences(settings),
                'storage':'github' if metadata and metadata['storage']=='github' else 'local',
                'github_url':self.documents.content.url(guide,metadata['commit_sha']) if metadata and metadata['storage']=='github' else None,
                'commit_sha':metadata.get('commit_sha') if metadata else None,
                'note':{'text':read_document(note) or '', 'hash':documents[note]['hash'] if note in documents else None},
                'guide':read_document(guide,a.get('guide')),
                'summary':read_document(base+'/详细总结.md'),'english_learning':read_document(base+'/英语学习.md'),
                'full_text':full_text,
                'content_needs_refresh':a.get('content_version')!=2 and a.get('import_method') not in ('paste','url'),
                'content_job':latest,'path':guide}

    def path(self,relative):
        if not isinstance(relative,str) or not relative.startswith('认知阅读/') or '..' in relative.split('/'):
            fail('invalid','阅读文件路径无效。',422)
        return ContentPath(self.documents,relative)

    def hash(self,relative):return self.documents.hash(relative)

    def export(self,files,records,expected=None):
        self.recover_exports()
        for rel,h in (expected or {}).items():
            if self.hash(rel)!=h:fail('conflict','内容已更新，请重新读取：'+rel)
        journal={'id':'export-'+uuid.uuid4().hex,'type':'export','state':'pending',
                 'files':{rel:{'before':self.hash(rel),'text':text} for rel,text in files.items()},'records':records}
        self.put(TABLE,journal['id'],journal)
        self.finish_export(journal)

    def finish_export(self,journal):
        files={rel:item['text'] for rel,item in journal['files'].items()}
        expected={rel:item['before'] for rel,item in journal['files'].items()}
        for rel,old in expected.items():
            if self.hash(rel) not in (old,digest(files[rel])):fail('conflict','阅读资料已变化，请先核对：'+rel)
        sql=[('INSERT INTO reading_records VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
              [record['id'],encoded(record)]) for record in journal['records']]
        done={**journal,'state':'done'}
        sql.append(('UPDATE reading_records SET data=? WHERE id=?',[encoded(done),journal['id']]))
        return self.documents.publish(journal['id'],{'export':journal['id']},files,sql,{'id':journal['id']})

    def restore_article_index(self,missing_only=False):
        with self.lock():
            # Rebuild only from registered database documents and immutable GitHub
            # versions. Startup never scans local directories or edits live records.
            records=[]
            with self.conn() as c:existing={r[0]:json.loads(r[1]) for r in c.execute('SELECT id,data FROM reading_records')}
            for path in self.documents.names('认知阅读/文章资料/'):
                if not path.endswith('/文章信息.json'):continue
                aid=path.split('/')[2];old=existing.get(aid)
                if old and old.get('type')!='article':fail('migration_conflict','文章编号与已有记录冲突。')
                if old and missing_only:continue
                try:data=json.loads(self.documents.read(path))
                except (ValueError,TypeError):fail('migration_invalid','文章信息不是有效 JSON，来源原文保留。')
                if old:
                    # Existing personal state and drafts always win over file mirrors.
                    data={**data,**old}
                validate_article_source(data,aid)
                hashes={p:self.documents.hash(p) for p in self.documents.names('认知阅读/文章资料/'+aid+'/')}
                data['hashes']={**data.get('hashes',{}),**hashes}
                guide='认知阅读/文章资料/'+aid+'/中文导读.md'
                if self.documents.metadata(guide):data['guide']=self.documents.read(guide)
                full='认知阅读/文章资料/'+aid+'/原文.md'
                if not data.get('full_content') and self.documents.metadata(full):data['full_content']=self.documents.read(full)
                for field in ('read','read_later','bookmarked','archived'):data.setdefault(field,False)
                data.setdefault('language','zh');data.setdefault('author','未知');data.setdefault('summary','')
                records.append(data)
            if not records:return 0
            with self.conn() as c:
                for item in records:c.execute('INSERT INTO reading_records VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',(item['id'],encoded(item)))
            return len(records)


def make_store(root,db):
    return CloudReadingStore(root,db) if enabled() else ReadingStore(root,db)

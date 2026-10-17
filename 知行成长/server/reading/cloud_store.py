"""Reading metadata and notes in PostgreSQL; adopted article documents in GitHub."""
import json
import uuid
from contextlib import contextmanager
from urllib.parse import urlsplit

from cloud_content import Documents, ContentPath, enabled
from copilot.core import digest, encoded, fail, now, Problem
from legacy_schema import migrate
from .store import ReadingStore, TABLE, DEFAULT
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

    def generation_gate(self):return self.documents.generation_gate()

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

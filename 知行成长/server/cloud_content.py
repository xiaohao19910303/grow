"""Immutable GitHub documents and private database documents with durable publications."""
import json
import os
import posixpath
import threading
from contextlib import contextmanager
from pathlib import PurePosixPath
from urllib.parse import quote

from copilot.core import digest, encoded, fail, now, Problem
from plans.github import GitHubContent

ROOTS = ('每日认知与通识学习','认知阅读')
TABLES = '''
CREATE TABLE IF NOT EXISTS cloud_documents (path TEXT PRIMARY KEY,data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cloud_publications (id TEXT PRIMARY KEY,data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cloud_content_settings (id TEXT PRIMARY KEY,data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cloud_file_imports (id TEXT PRIMARY KEY,data TEXT NOT NULL);
'''


def valid_path(path):
    if (not isinstance(path,str) or PurePosixPath(path).is_absolute() or
        '..' in PurePosixPath(path).parts or '\\' in path or any(ord(c)<32 for c in path) or
        str(PurePosixPath(path))!=path or path.split('/')[0] not in ROOTS):
        fail('invalid','资料路径无效。',422)
    return path


def is_formal(path):
    valid_path(path)
    parts=path.split('/')
    if not path.endswith('.md'):return False
    if parts[0]=='每日认知与通识学习':
        return parts[1] in ('每日课程','参考资料','备课资料') or '/'.join(parts[1:]) in ('学习规划.md','课程主题规划.md','课程目录.md')
    return len(parts)>3 and parts[1]=='文章资料'


class ModuleContent(GitHubContent):
    def __init__(self,repository,branch,token,transport=None,prefix=''):
        super().__init__(repository,branch,token,transport=transport)
        self.prefix=prefix
        self.read_lock=threading.RLock()

    def physical_path(self,relative):return self.prefix+relative

    def read_text(self,relative,ref=None,missing=False):
        with self.read_lock:return super().read_text(relative,ref,missing)

    def prepare(self,head,files,operation):
        for path in files:self.path(path)
        commit=self.request('GET','git/commits/'+head)
        entries=[{'path':self.physical_path(path),'mode':'100644','type':'blob','content':text} for path,text in files.items()]
        tree=self.request('POST','git/trees',json={'base_tree':commit['tree']['sha'],'tree':entries})
        return self.request('POST','git/commits',json={'message':'Publish learning content\n\nPublication: '+digest(operation),
            'tree':tree['sha'],'parents':[head]})['sha']

    def path(self,relative):
        valid_path(relative)
        if not is_formal(relative):fail('private_document','个人记录和配置不得发布到内容仓库。',422)
        return quote(self.physical_path(relative),safe='/')


def configured_content():
    # Preserve the account plugin's server-generated repository prefix when present.
    try:
        from tenancy import current_user
        user=current_user.get()
    except ImportError:user=None
    if user:
        from accounts import content_for
        base=content_for(user)
    else:base=GitHubContent.from_env()
    return ModuleContent(base.repository,base.branch,base.token,transport=base.transport,prefix=getattr(base,'prefix',''))


def enabled():
    if os.getenv('PLAN_CONTENT_BACKEND')=='github':return True
    try:
        from tenancy import current_user
        user=current_user.get()
        return bool(user and json.loads(user.get('github_config') or '{}').get('mode')=='custom')
    except ImportError:return False


class Documents:
    def __init__(self, store, content=None):
        self.store=store;self.local=threading.local();self.configuration_error=None
        try:self.content=content or configured_content()
        except Problem as exc:
            # Account login/settings must remain usable while credentials are repaired.
            self.configuration_error=exc;self.content=ModuleContent('','','')

    def get(self,table,key,column='id'):
        with self.store.conn() as c:r=c.execute(f'SELECT data FROM {table} WHERE {column}=?',(key,)).fetchone()
        return json.loads(r[0]) if r else None

    def put(self,table,key,value,column='id',connection=None):
        sql=f'INSERT INTO {table} VALUES (?,?) ON CONFLICT({column}) DO UPDATE SET data=excluded.data'
        if connection is not None:connection.execute(sql,(key,encoded(value)))
        else:
            with self.store.conn() as c:c.execute(sql,(key,encoded(value)))

    def rows(self,table):
        with self.store.conn() as c:return [(r[0],json.loads(r[1])) for r in c.execute(f'SELECT * FROM {table}')]

    @contextmanager
    def lock(self):
        if getattr(self.local,'locked',False):
            yield;return
        with self.store.conn() as c:
            schema=c.execute('SELECT current_schema()').fetchone()[0]
            # Also coordinate with the pre-account single-user plan writer.
            for identity in sorted({int(digest(name)[:15],16) for name in ('learning-plan-publications',schema+':learning-plan-publications')}):
                c.execute('SELECT pg_advisory_xact_lock(?)',(identity,))
            self.local.locked=True
            try:yield
            finally:self.local.locked=False

    @contextmanager
    def generation_gate(self):
        with self.store.conn() as c:
            schema=c.execute('SELECT current_schema()').fetchone()[0]
            for identity in sorted({int(digest(name)[:15],16) for name in ('learning-plan-generation',schema+':learning-plan-generation')}):
                ok=c.execute('SELECT pg_try_advisory_xact_lock(?)',(identity,)).fetchone()[0]
                if not ok:fail('generation_busy','另一个生成任务正在运行。')
            yield

    def initialize(self):
        if self.configuration_error:raise self.configuration_error
        self.content.validate()
        with self.store.conn() as c:c.executescript(TABLES)
        binding={'repository':self.content.repository,'branch':self.content.branch,'prefix':self.content.prefix}
        with self.lock():
            old=self.get('cloud_content_settings','binding')
            if old and old!=binding:
                published=any(item['storage']=='github' for _,item in self.rows('cloud_documents'))
                pending=any(item['state']!='done' for _,item in self.rows('cloud_publications'))
                if published or pending:fail('content_binding','资料已绑定其他仓库或分支，请先迁移，不能直接替换。',503)
                # Browser/account setup may choose a repository before the first publication.
                # Private database notes do not bind an account to an empty content repository.
            self.put('cloud_content_settings','binding',binding)
            try:self.recover()
            except Problem as exc:
                if exc.code not in ('content_conflict','conflict','github_conflict','github_unavailable','github_access'):raise

    def metadata(self,path):
        return self.get('cloud_documents',valid_path(path),'path')

    def read(self,path):
        item=self.metadata(path)
        if item is None:raise FileNotFoundError(path)
        text=self.content.read_text(path,item['commit_sha']) if item['storage']=='github' else item['text']
        if digest(text)!=item['hash']:fail('content_hash','内容校验失败，已停止读写。',409)
        return text

    def hash(self,path):
        item=self.metadata(path)
        return item['hash'] if item else None

    def names(self,prefix=''):
        return [path for path,_ in self.rows('cloud_documents') if path.startswith(prefix)]

    def recover(self):
        for key,journal in self.rows('cloud_publications'):
            if journal['state']!='done':
                try:self.finish(key,journal)
                except Problem as exc:
                    journal.update(error=exc.code,message=exc.message)
                    self.put('cloud_publications',key,journal)
                    raise

    def publish(self,key,request,files,sql=(),result=None,expected=None,guards=None,adopt_existing=False):
        with self.lock():
            old=self.get('cloud_publications',key)
            fingerprint=digest(encoded(request))
            if old:
                if old['request']!=fingerprint:fail('conflict','相同请求标识不能用于不同内容。')
                if old['state']!='done':self.finish(key,old)
                return old['result']
            self.recover()
            for path,text in files.items():
                valid_path(path)
                if not isinstance(text,str) or len(text.encode())>1_000_000:fail('invalid','资料须为不超过 1 MB 的 UTF-8 文本。',422)
            for path,old_hash in (expected or {}).items():
                if self.hash(path)!=old_hash:fail('conflict','内容已更新，请重新读取：'+path)
            changes={path:{'before':self.hash(path),'after':digest(text),'text':text,'formal':is_formal(path)} for path,text in files.items()}
            journal={'id':key,'request':fingerprint,'state':'pending','files':changes,'sql':list(sql),'result':result or {},
                     'guards':guards or {},'adopt_existing':adopt_existing,'created_at':now(),'binding':self.get('cloud_content_settings','binding')}
            self.put('cloud_publications',key,journal)
            self.finish(key,journal)
            return journal['result']

    def finish(self,key,journal):
        if journal['binding']!=self.get('cloud_content_settings','binding'):fail('content_binding','待恢复发布属于其他仓库。')
        public={p:x for p,x in journal['files'].items() if x['formal']}
        if public:
            head=self.content.head()
            if head is None:self.content.bootstrap();head=self.content.head()
            candidate=journal.get('commit_sha')
            reached=candidate and self.content.contains(candidate,head)
            if not reached:
                for path,expected in {**journal['guards'],**{p:x['before'] for p,x in public.items()}}.items():
                    current=self.content.read_text(path,head,missing=True)
                    actual=digest(current) if current is not None else None
                    # Import may adopt identical already-published documents, never an edit.
                    if actual!=expected and not (journal.get('adopt_existing') and path in public and actual==public[path]['after']):
                        fail('content_conflict','GitHub 文件已变化，原数据保留，请核对：'+path)
                if not candidate or journal.get('parent_sha')!=head:
                    candidate=self.content.prepare(head,{p:x['text'] for p,x in public.items()},key)
                    journal.update(commit_sha=candidate,parent_sha=head)
                    self.put('cloud_publications',key,journal)
                self.content.advance(candidate)
            for path,change in public.items():
                if digest(self.content.read_text(path,candidate))!=change['after']:fail('content_hash','GitHub 提交校验失败。')
        with self.store.conn() as c:
            schema=c.execute('SELECT current_schema()').fetchone()[0]
            for path in sorted(journal['files']):
                change=journal['files'][path]
                c.execute('SELECT pg_advisory_xact_lock(?)',(int(digest(schema+':document:'+path)[:15],16),))
                # Pending publications are replayed before subsequent writes under the same lock.
                row=c.execute('SELECT data FROM cloud_documents WHERE path=? FOR UPDATE',(path,)).fetchone()
                before=json.loads(row[0]) if row else None
                if (before['hash'] if before else None) not in (change['before'],change['after']):fail('conflict','发布期间数据库资料已变化。')
                item={'hash':change['after'],'storage':'github' if change['formal'] else 'database','updated_at':now()}
                if change['formal']:item['commit_sha']=journal['commit_sha']
                else:item['text']=change['text']
                self.put('cloud_documents',path,item,'path',c)
            for statement,params in journal['sql']:c.execute(statement,params)
            journal['state']='done';journal['finished_at']=now()
            journal['result'].update(storage='github' if public else 'database')
            if public:journal['result']['commit_sha']=journal['commit_sha']
            self.put('cloud_publications',key,journal,connection=c)


class ContentPath:
    """Small read-only path facade for the existing parsers; no temporary checkout."""
    def __init__(self,documents,path):self.documents=documents;self.value=posixpath.normpath(str(path))
    def __str__(self):return self.value
    def __lt__(self,other):return self.value<str(other)
    def __eq__(self,other):return self.value==str(other)
    def __truediv__(self,other):return ContentPath(self.documents,self.value+'/'+str(other))
    @property
    def name(self):return PurePosixPath(self.value).name
    @property
    def stem(self):return PurePosixPath(self.value).stem
    @property
    def parent(self):return ContentPath(self.documents,str(PurePosixPath(self.value).parent))
    def resolve(self):return self
    def relative_to(self,other):return PurePosixPath(self.value).relative_to(str(other))
    def is_relative_to(self,other):return PurePosixPath(self.value).is_relative_to(str(other))
    def exists(self):return self.is_file() or self.is_dir()
    def is_file(self):return self.documents.metadata(self.value) is not None
    def is_dir(self):return bool(self.documents.names(self.value+'/')) or self.value.split('/')[-1] in ('每日课程','参考资料','备课资料','文章资料')
    def is_symlink(self):return False
    def read_text(self,encoding='utf-8'):return self.documents.read(self.value)
    def read_bytes(self):return self.read_text().encode('utf-8')
    def mkdir(self,**kwargs):pass
    def glob(self,pattern):
        prefix=self.value+'/'
        for path in self.documents.names(prefix):
            suffix=path[len(prefix):]
            if PurePosixPath(suffix).match(pattern) and ('/' in pattern or '/' not in suffix):yield ContentPath(self.documents,path)

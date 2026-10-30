"""Database-indexed immutable research archives; filesystem failures never undo research."""
import copy
import gzip
import io
import json
import os
import zipfile
from pathlib import Path

import db
from fastapi import Header,Query
from fastapi.responses import Response
from pydantic import Field
from copilot.core import fail,now,Problem
from .contracts import Contract,Identifier
from .research_files import ArchiveFiles,ArchiveFileError,canonical,checksum,LIMIT

KINDS={'dataset','series','screen','backtest','comparison'}
TABLES='''CREATE TABLE IF NOT EXISTS investment_research_archives (
 object_id TEXT NOT NULL, version INTEGER NOT NULL, data TEXT NOT NULL,
 PRIMARY KEY(object_id,version), FOREIGN KEY(object_id,version) REFERENCES investment_research_versions(object_id,version));'''
BULK={'rows','bars','evaluations','items','trades','equity','orders','changes'}


def artifacts(record):
    value=copy.deepcopy(record);files={};segments=[]
    def walk(node,path):
        if not isinstance(node,dict):return
        for name in list(node):
            child=node[name];pointer=[*path,name]
            if name in BULK and isinstance(child,list):
                filename='_'.join(pointer)+'.jsonl.gz'
                files[filename]=gzip.compress(b''.join(canonical(row)+b'\n' for row in child),mtime=0)
                segments.append({'path':pointer,'file':filename});del node[name]
            elif isinstance(child,dict):walk(child,pointer)
    walk(value['data'],[])
    files['record.json']=canonical({'record':value,'segments':segments})
    return files


def unpack(files):
    envelope=json.loads(files['record.json']);record=envelope['record'];total=len(files['record.json'])
    for segment in envelope['segments']:
        with gzip.GzipFile(fileobj=io.BytesIO(files[segment['file']])) as stream:raw=stream.read(LIMIT+1)
        total+=len(raw)
        if total>LIMIT:raise ArchiveFileError('归档解压大小超限。')
        target=record['data']
        for part in segment['path'][:-1]:target=target[part]
        target[segment['path'][-1]]=[json.loads(row) for row in raw.splitlines()]
    return record


def public(status):return {k:v for k,v in status.items() if k not in ('key',)}


class ResearchArchive:
    def __init__(self,service):self.service=service;self.root=os.getenv('INVESTMENT_RESEARCH_ARCHIVE_ROOT','')
    def initialize(self,c):self.service.initialize(c);c.executescript(TABLES)
    def record(self,c,identity,version,account_id):
        current=self.service.get(c,identity,account_id=account_id)
        if current['kind'] not in KINDS:fail('archive_kind','此类记录暂不归档，请选择数据集、筛选、历史、回测或对比。',422)
        version=version or current['version']
        row=c.execute('SELECT data FROM investment_research_versions WHERE object_id=? AND version=?',(identity,version)).fetchone()
        if not row:fail('not_found','研究记录版本不存在。',404)
        return json.loads(row[0])
    @staticmethod
    def parents(record):
        data=record['data'];kind=record['kind']
        if kind=='screen':return [{'id':data['request']['dataset_id'],'version':1,'input_hash':data['dataset_hash']}]
        if kind=='backtest':return [{'id':data['request']['series_id'],'version':1,'input_hash':data['series_hash']}]
        return data['sources'] if kind=='comparison' else []
    def state(self,c,identity,version):
        row=c.execute('SELECT data FROM investment_research_archives WHERE object_id=? AND version=?',(identity,version)).fetchone()
        return json.loads(row[0]) if row else None
    def save_state(self,c,record,state,**extra):
        data={'object_id':record['id'],'version':record['version'],'account_id':record['account_id'],'kind':record['kind'],'state':state,'updated_at':now(),**extra}
        c.execute('INSERT INTO investment_research_archives VALUES (?,?,?) ON CONFLICT(object_id,version) DO UPDATE SET data=excluded.data',(record['id'],record['version'],canonical(data).decode()))
        return data
    def write(self,identity,version,account_id,retry=True):
        if not self.root:fail('archive_disabled','服务端尚未配置研究归档目录，已保存的数据库资料不受影响。',503)
        with db.connect() as c:
            self.initialize(c);record=self.record(c,identity,version,account_id);previous=self.state(c,identity,record['version'])
            if previous and previous['state']!='pending' and not retry:return public(previous)
            schema=c.execute('SELECT current_schema()').fetchone()[0]
            key=(checksum(schema.encode())[:32],checksum(account_id.encode())[:32], 'datasets' if record['kind'] in ('dataset','series') else 'comparisons' if record['kind']=='comparison' else 'runs',checksum(identity.encode()),'v'+str(record['version']))
            self.save_state(c,record,'pending',key=list(key))
        try:
            references=self.parents(record)
            for parent in references:
                with db.connect() as c:
                    self.initialize(c);frozen=self.record(c,parent['id'],parent['version'],account_id)
                    if frozen['input_hash']!=parent['input_hash']:fail('archive_reference','冻结资料引用不一致，未归档。',409)
                state=self.write(parent['id'],parent['version'],account_id,retry)
                if state['state']!='ready':raise ArchiveFileError('依赖资料尚未归档。')
            data=record['data'];source_keys=('source_label','market_date','captured_at','source_units','source_verification','market_date_verification','coverage','actual_count','expected_count','price_basis','interval','calendar_status','adapter_version','upstream','known_at')
            metadata={'writer_version':'research-archive-v1','record_id':identity,'version':record['version'],'account_id':account_id,
                'tenant_key':key[0],'kind':record['kind'],'record_hash':checksum(canonical(record)),'input_hash':record['input_hash'],
                'source':{k:data[k] for k in source_keys if k in data},'references':references,
                'algorithm':data.get('algorithm') or data.get('result',{}).get('algorithm'),
                'timezone':'Asia/Shanghai','currency':'CNY','normalized_units':{'price':'cny','volume':'shares','amount':'cny'},
                'supplier_raw_payload_included':False,'payload_scope':'已保存的数据库冻结版本，非供应商原始报文。'}
            written=ArchiveFiles(self.root).write(key,metadata,artifacts(record))
            with db.connect() as c:
                self.initialize(c);state=self.save_state(c,record,'ready',**written,verified_at=now(),reason=None)
            return public(state)
        except Exception:
            # Only a fixed message is persisted. OS/DB/provider exception strings
            # can contain credentials, private source text or machine paths.
            with db.connect() as c:
                self.initialize(c);state=self.save_state(c,record,'failed',key=list(key),reason='归档未完成或原文件有冲突，请检查磁盘及原归档后主动重试。')
            return public(state)
    def ensure(self,record):
        if not self.root or record['kind'] not in KINDS:return
        try:self.write(record['id'],record['version'],record['account_id'],retry=False)
        except Exception:pass  # Business commit already succeeded; status can be queried/retried separately.
    def verified(self,identity,version,account_id):
        if not self.root:fail('archive_disabled','研究归档目录未配置。',503)
        with db.connect() as c:
            self.initialize(c);record=self.record(c,identity,version,account_id);state=self.state(c,identity,record['version'])
        if not state or state['state']!='ready':fail('archive_not_ready','该版本尚无可验证的归档，请先归档或重试。',409)
        try:
            manifest,files=ArchiveFiles(self.root).read(state['key'],state['manifest_hash'])
            if manifest.get('record_hash')!=checksum(canonical(record)) or files!=artifacts(record):raise ArchiveFileError('冻结版本与归档不一致。')
            if unpack(files)!=record:raise ArchiveFileError('归档还原不一致。')
            return record,state,manifest,files
        except (ArchiveFileError,ValueError,KeyError,TypeError):
            with db.connect() as c:
                self.initialize(c);self.save_state(c,record,'damaged',key=state['key'],manifest_hash=state['manifest_hash'],reason='归档缺失或哈希不符；已阻止下载，原目录及数据库版本保留。')
            fail('archive_damaged','归档缺失或校验失败，下载已阻止；请保留现场并核对备份。',409)
    def read_record(self,identity,version,account_id):return unpack(self.verified(identity,version,account_id)[3])
    def verify(self,identity,version,account_id):
        seen=set()
        def visit(identity,version):
            if (identity,version) in seen:return None
            if len(seen)>=100:fail('archive_reference','归档依赖层级超限。',409)
            seen.add((identity,version));record,state,manifest,files=self.verified(identity,version,account_id)
            for parent in self.parents(record):
                frozen=self.verified(parent['id'],parent['version'],account_id)[0]
                if frozen['input_hash']!=parent['input_hash']:fail('archive_reference','归档引用哈希不一致。',409)
                visit(parent['id'],parent['version'])
            return state
        state=visit(identity,version)
        with db.connect() as c:
            self.initialize(c);record=self.record(c,identity,version,account_id)
            state=self.save_state(c,record,'ready',**{k:v for k,v in state.items() if k not in ('object_id','version','account_id','kind','state','updated_at','verified_at')},verified_at=now())
        return public(state)
    def download(self,identity,version,account_id):
        output=io.BytesIO();seen=set();total=0;entries=[]
        with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            def append(identity,version):
                nonlocal total
                if (identity,version) in seen:return
                seen.add((identity,version));record,state,manifest,files=self.verified(identity,version,account_id)
                prefix='objects/'+checksum(identity.encode())+'-v'+str(version)+'/'
                for name,data in {'manifest.json':canonical(manifest),**files}.items():
                    total+=len(data)
                    if total>LIMIT:fail('archive_size','该归档及引用超过100MB，请使用管理员完整备份。',422)
                    archive.writestr(prefix+name,data)
                entries.append({'object_id':identity,'version':version,'directory':prefix,'manifest_hash':state['manifest_hash']})
                for parent in self.parents(record):append(parent['id'],parent['version'])
            append(identity,version);archive.writestr('bundle.json',canonical({'format':'grow-research-bundle-v1','records':entries}))
        return output.getvalue()
    def listing(self,account_id,page=1,page_size=50):
        with db.connect() as c:
            self.initialize(c);self.service.store._get(c,'accounts',account_id)
            total=c.execute("SELECT count(*) FROM investment_research_objects WHERE account_id=? AND kind IN ('dataset','series','screen','backtest','comparison')",(account_id,)).fetchone()[0]
            rows=c.execute("SELECT o.data AS record_data,a.data AS archive_data FROM investment_research_objects o LEFT JOIN investment_research_archives a ON a.object_id=o.id AND a.version=o.version WHERE o.account_id=? AND o.kind IN ('dataset','series','screen','backtest','comparison') ORDER BY o.data::jsonb->>'created_at' DESC,o.id DESC LIMIT ? OFFSET ?",(account_id,page_size,(page-1)*page_size)).fetchall()
        items=[]
        for row in rows:
            raw,status=row[0],row[1]
            record=json.loads(raw);item=json.loads(status) if status else {'object_id':record['id'],'version':record['version'],'kind':record['kind'],'state':'unarchived' if self.root else 'disabled','reason':None}
            items.append({**public(item),'created_at':record['created_at'],'name':record['data'].get('name') or record['data'].get('source_label') or record['kind']})
        return {'enabled':bool(self.root),'items':items,'total':total,'page':page,'page_size':page_size}


class ArchiveRequest(Contract):
    account_id:Identifier
    object_id:Identifier
    version:int=Field(ge=1)


def register(router,service):
    archive=ResearchArchive(service)
    @router.get('/research/archives')
    def listing(account_id:str,page:int=Query(1,ge=1),page_size:int=Query(50,ge=1,le=100)):return archive.listing(account_id,page,page_size)
    @router.post('/research/archives')
    def write(payload:ArchiveRequest):return archive.write(payload.object_id,payload.version,payload.account_id)
    @router.post('/research/archives/verify')
    def verify(payload:ArchiveRequest):return archive.verify(payload.object_id,payload.version,payload.account_id)
    @router.get('/research/archives/{identity}/download')
    def download(identity:str,account_id:str,version:int=Query(ge=1)):
        return Response(archive.download(identity,version,account_id),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="research-archive.zip"','Cache-Control':'no-store'})
    return archive

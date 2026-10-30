"""Offline full-backup companion. Explicit entries only; never extract arbitrary ZIP paths."""
import json
import os
import stat
import zipfile
from pathlib import Path
from psycopg2 import sql
from .research_files import ArchiveFiles,ArchiveFileError,canonical,checksum,LIMIT,NAME
from .research_archive import artifacts,unpack,ResearchArchive

FILENAME='research-archives.zip'


def records(connection):
    cur=connection.cursor();cur.execute("SELECT schemaname FROM pg_tables WHERE tablename='investment_research_archives' AND schemaname NOT LIKE 'pg_%' ORDER BY 1")
    schemas=[r[0] for r in cur.fetchall()];result=[]
    for schema in schemas:
        cur.execute(sql.SQL('SELECT a.data,v.data FROM {}.investment_research_archives a JOIN {}.investment_research_versions v ON v.object_id=a.object_id AND v.version=a.version ORDER BY a.object_id,a.version').format(sql.Identifier(schema),sql.Identifier(schema)))
        for state,record in cur.fetchall():
            state,record=json.loads(state),json.loads(record)
            if state['state']=='damaged':raise ArchiveFileError('存在损坏归档，请先核对原归档和备份。')
            if state['state']=='ready':result.append((schema,state,record))
    return result


def expected_key(schema,record):
    return [checksum(schema.encode())[:32],checksum(record['account_id'].encode())[:32],'datasets' if record['kind'] in ('dataset','series') else 'comparisons' if record['kind']=='comparison' else 'runs',checksum(record['id'].encode()),'v'+str(record['version'])]


def check_record(schema,state,record,manifest,files):
    if state['key']!=expected_key(schema,record) or checksum(canonical(record))!=manifest.get('record_hash') or files!=artifacts(record) or unpack(files)!=record:raise ArchiveFileError('归档与数据库冻结记录不一致。')
    if manifest.get('references')!=ResearchArchive.parents(record):raise ArchiveFileError('归档引用不一致。')


def create(connection,root,destination):
    saved=records(connection)
    if not saved:return None
    if not root:raise ArchiveFileError('数据库含已归档引用，完整备份必须配置研究归档根目录。')
    store=ArchiveFiles(root);index=[];available={(schema,record['id'],record['version']):record for schema,_,record in saved}
    with zipfile.ZipFile(destination,'w',compression=zipfile.ZIP_DEFLATED) as bundle:
        for schema,state,record in saved:
            manifest,files=store.read(state['key'],state['manifest_hash']);check_record(schema,state,record,manifest,files)
            for parent in ResearchArchive.parents(record):
                ref=available.get((schema,parent['id'],parent['version']))
                if not ref or ref['input_hash']!=parent['input_hash']:raise ArchiveFileError('归档依赖未完整备份。')
            prefix='/'.join(state['key'])+'/'
            for name,data in {'manifest.json':canonical(manifest),**files}.items():bundle.writestr(prefix+name,data)
            index.append({'key':state['key'],'manifest_hash':state['manifest_hash']})
        bundle.writestr('archive-index.json',canonical({'format':'grow-research-full-backup-v1','records':index}))
    return {'file':FILENAME,'count':len(index),'format':'grow-research-full-backup-v1'}


def entries(path):
    """Yield validated records from a bounded ZIP; caller may publish in a new root."""
    try:
        with zipfile.ZipFile(path) as bundle:
            infos=bundle.infolist();names=[i.filename for i in infos]
            if len(names)!=len(set(names)) or len(names)>500000 or any(i.is_dir() or stat.S_ISLNK(i.external_attr>>16) or i.file_size>LIMIT for i in infos):raise ArchiveFileError('归档备份条目无效。')
            info=bundle.getinfo('archive-index.json')
            if info.file_size>10_000_000:raise ArchiveFileError('归档索引过大。')
            index=json.loads(bundle.read(info))
            if index.get('format')!='grow-research-full-backup-v1' or not isinstance(index.get('records'),list) or len(index['records'])>20000:raise ArchiveFileError('归档索引无效。')
            expected={'archive-index.json'};seen=set()
            for item in index['records']:
                key=ArchiveFiles.key(item['key']);prefix='/'.join(key)+'/'
                if key in seen:raise ArchiveFileError('重复的归档身份。')
                seen.add(key);mi=bundle.getinfo(prefix+'manifest.json')
                if mi.file_size>128000:raise ArchiveFileError('归档清单过大。')
                raw=bundle.read(mi)
                if checksum(raw)!=item['manifest_hash']:raise ArchiveFileError('归档清单哈希不匹配。')
                manifest=json.loads(raw);descriptions=manifest['files']
                if manifest.get('format')!='grow-research-archive-v1' or not 1<=len(descriptions)<=24:raise ArchiveFileError('归档清单无效。')
                files={};total=0;expected.add(prefix+'manifest.json')
                for name,description in descriptions.items():
                    if not NAME.fullmatch(name) or name=='manifest.json':raise ArchiveFileError('归档文件名无效。')
                    fi=bundle.getinfo(prefix+name);total+=fi.file_size
                    if total>LIMIT or fi.file_size!=description['size']:raise ArchiveFileError('归档大小不符。')
                    data=bundle.read(fi)
                    if checksum(data)!=description['sha256']:raise ArchiveFileError('归档文件哈希不符。')
                    files[name]=data;expected.add(prefix+name)
                # Validate reconstructibility even in verify-only mode.
                record=unpack(files)
                if checksum(canonical(record))!=manifest.get('record_hash'):raise ArchiveFileError('归档记录哈希不符。')
                yield key,item['manifest_hash'],manifest,files
            if expected!=set(names):raise ArchiveFileError('归档备份含未声明条目。')
    except (OSError,ValueError,KeyError,TypeError,zipfile.BadZipFile,RuntimeError) as error:raise ArchiveFileError('研究归档备份校验失败。') from error


def verify(path,count):
    if sum(1 for _ in entries(path))!=count:raise ArchiveFileError('归档数量不符。')


def restore(path,root,count):
    root=Path(root)
    if not root.is_absolute() or root.exists() or root.is_symlink():raise ArchiveFileError('归档恢复必须使用新的绝对目录。')
    verify(path,count);root.mkdir(mode=0o700,parents=True)
    for key,expected,manifest,files in entries(path):
        metadata={k:v for k,v in manifest.items() if k not in ('format','files')};written=ArchiveFiles(root).write(key,metadata,files)
        if written['manifest_hash']!=expected:raise ArchiveFileError('归档恢复哈希不符。')


def verify_database(connection,root,count):
    saved=records(connection)
    if len(saved)!=count:raise ArchiveFileError('数据库归档引用数量不符。')
    for schema,state,record in saved:
        manifest,files=ArchiveFiles(root).read(state['key'],state['manifest_hash']);check_record(schema,state,record,manifest,files)

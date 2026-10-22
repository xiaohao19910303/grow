"""Offline administrator backup/restore for standalone PostgreSQL + GitHub content.
Stop all writers first. Git mirrors are supplied by the administrator; no remote writes.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import parse_dsn
from cryptography.fernet import Fernet, InvalidToken


class BackupError(ValueError):pass


def command(args, env=None):
    try:
        return subprocess.run(args, env=env, check=True, capture_output=True, text=True, timeout=300).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        raise BackupError('备份工具执行失败：' + Path(args[0]).name + '；请检查版本、权限和容量。') from None


def pg_env(dsn):
    settings = parse_dsn(dsn)
    if settings.get('options'):
        raise BackupError('仅支持整个独立数据库，DATABASE_URL 不得设置 search_path/options。')
    env = {k:v for k,v in os.environ.items() if not k.startswith('PG')}
    for key in ('host','port','user','password','dbname','sslmode','sslrootcert','sslcert','sslkey','connect_timeout'):
        if key in settings:env['PG' + ('DATABASE' if key=='dbname' else key.upper())] = settings[key]
    env['PGCONNECT_TIMEOUT']='10'
    return env


def fingerprint(key):
    try:Fernet(key.encode())
    except (ValueError,AttributeError):raise BackupError('ACCOUNT_ENCRYPTION_KEY 无效。') from None
    return hashlib.sha256(key.encode()).hexdigest()


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def inventory(connection, env):
    cur=connection.cursor()
    cur.execute("SELECT schemaname,tablename FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') AND schemaname NOT LIKE 'pg_toast%%' ORDER BY 1,2")
    tables=cur.fetchall();counts={};hashes={};schemas={}
    default=env.get('GITHUB_CONTENT_REPO','');branch=env.get('GITHUB_CONTENT_BRANCH','main')
    # Every tenant is represented by its actual schema, not just the current login.
    for schema,table in tables:
        cur.execute(sql.SQL('SELECT row_to_json(t)::text FROM {}.{} t ORDER BY row_to_json(t)::text').format(sql.Identifier(schema),sql.Identifier(table)))
        raw_rows=[row[0] for row in cur.fetchall()]
        rows=[json.loads(row) for row in raw_rows]
        name=schema+'.'+table;counts[name]=len(rows)
        hashes[name]=hashlib.sha256(('\n'.join(raw_rows)).encode()).hexdigest()
        entry=schemas.setdefault(schema,{'bindings':set(),'refs':set()})
        if table=='auth_users':
            for row in rows:
                cfg=json.loads(row.get('github_config') or '{}')
                target=schemas.setdefault(row['schema_name'],{'bindings':set(),'refs':set()})
                if cfg.get('mode')=='custom':
                    try:Fernet(env['ACCOUNT_ENCRYPTION_KEY'].encode()).decrypt(cfg['token'].encode())
                    except (InvalidToken,KeyError):raise BackupError('账号凭证不能用当前加密密钥解密，请恢复原密钥。') from None
                    target['bindings'].add((cfg['repository'],cfg['branch']))
        # Only publication/storage metadata is inspected for content refs. Private bodies
        # remain in the database dump and never enter the manifest or logs.
        if table in ('cloud_documents','cloud_publications','cloud_content_settings','learning_lessons','learning_publications','learning_settings','study_generated_courses'):
            def scan(value):
                if isinstance(value,dict):
                    if value.get('repository') and value.get('branch'):entry['bindings'].add((value['repository'],value['branch']))
                    for key,v in value.items():
                        if key in ('commit_sha','parent_sha') and v:
                            if not isinstance(v,str) or not re.fullmatch('[0-9a-f]{40}',v):raise BackupError('正式内容版本引用无效。')
                            entry['refs'].add(v)
                        elif isinstance(v,(dict,list)):scan(v)
                elif isinstance(value,list):
                    for v in value:scan(v)
            for row in rows:
                data=row.get('data')
                if isinstance(data,str):
                    try:data=json.loads(data)
                    except json.JSONDecodeError:continue
                scan(data)
    repositories={}
    for schema,entry in schemas.items():
        bindings=entry['bindings']
        if not bindings and entry['refs']:
            if not default:raise BackupError('缺少正式内容仓库绑定，不能生成完整备份。')
            bindings.add((default,branch))
        if entry['refs'] and len(bindings)>1:raise BackupError('同一 schema 有多个内容绑定，需先核对版本归属。')
        for repo,ref in bindings:
            if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):raise BackupError('内容仓库名称无效。')
            item=repositories.setdefault(repo,{'branches':set(),'commits':set(),'schemas':set()})
            item['branches'].add(ref);item['commits'].update(entry['refs']);item['schemas'].add(schema)
    return {'tables':counts,'row_hashes':hashes,'repositories':{k:{a:sorted(b) for a,b in v.items()} for k,v in sorted(repositories.items())}}


def create(dsn, destination, mirrors, *, env=None, writers_stopped=False):
    env=os.environ if env is None else env
    if not writers_stopped:raise BackupError('必须先停止网页、定时任务及所有写入，再传 --writers-stopped。')
    destination=Path(destination).absolute()
    if destination.exists():raise BackupError('备份目标已存在；请使用新的目录。')
    key_hash=fingerprint(env.get('ACCOUNT_ENCRYPTION_KEY'))
    subprocess_env=pg_env(dsn)
    staging=Path(tempfile.mkdtemp(prefix='.grow-backup-',dir=destination.parent));os.chmod(staging,0o700)
    try:
        with psycopg2.connect(dsn,connect_timeout=10) as connection:
            connection.set_session(isolation_level='REPEATABLE READ',readonly=True)
            cur=connection.cursor();cur.execute('SELECT pg_export_snapshot(), current_database(), current_setting(\'server_version\')');snapshot,dbname,pgversion=cur.fetchone()
            contents=inventory(connection,env)
            for repo in contents['repositories']:
                if repo not in mirrors:raise BackupError('缺少内容镜像：'+repo)
            command(['pg_dump','--format=custom','--no-owner','--no-acl','--snapshot='+snapshot,'--file='+str(staging/'database.dump')],subprocess_env)
            for index,(repo,item) in enumerate(contents['repositories'].items()):
                mirror=Path(mirrors[repo]).resolve()
                if command(['git','--git-dir',str(mirror),'rev-parse','--is-bare-repository'])!='true':raise BackupError('内容镜像必须是 bare Git 仓库。')
                with tempfile.TemporaryDirectory(prefix='grow-content-') as tmp:
                    clone=Path(tmp)/'content.git'
                    command(['git','clone','--mirror','--no-hardlinks',str(mirror),str(clone)])
                    for ref in item['branches']:
                        command(['git','--git-dir',str(clone),'rev-parse','--verify','refs/heads/'+ref+'^{commit}'])
                    for sha in item['commits']:
                        command(['git','--git-dir',str(clone),'fetch','--no-write-fetch-head',str(mirror),sha])
                        command(['git','--git-dir',str(clone),'update-ref','refs/grow-backup/'+sha,sha])
                    filename='content-'+str(index)+'.bundle'
                    command(['git','--git-dir',str(clone),'bundle','create',str(staging/filename),'--all'])
                    item['bundle']=filename
        root=Path(__file__).resolve().parents[2]
        try:revision=command(['git','-C',str(root),'rev-parse','HEAD'])
        except BackupError:revision=env.get('GROW_REVISION') or env.get('RENDER_GIT_COMMIT','')
        if not re.fullmatch('[0-9a-f]{40}',revision):raise BackupError('缺少可核对的代码版本，请设置 GROW_REVISION 为候选完整 SHA。')
        manifest={'version':1,'created_at':datetime.now(timezone.utc).isoformat(),'application_revision':revision,
                  'postgres_version':pgversion,'source_database':dbname,'encryption_key_sha256':key_hash,
                  'default_content':{'repository':env.get('GITHUB_CONTENT_REPO',''),'branch':env.get('GITHUB_CONTENT_BRANCH','main')},
                  'excluded':['browser_drafts','browser_ai_config','external_credentials','runtime_cache'],**contents}
        manifest['files']={p.name:digest(p) for p in staging.iterdir()}
        (staging/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        for file in staging.iterdir():os.chmod(file,0o600)
        staging.rename(destination)
        return manifest
    finally:
        if staging.exists():shutil.rmtree(staging)


def verify(directory):
    directory=Path(directory)
    try:
        manifest=json.loads((directory/'manifest.json').read_text())
        if manifest['version']!=1 or 'database.dump' not in manifest['files']:raise ValueError()
        expected={'database.dump',*(r['bundle'] for r in manifest['repositories'].values())}
        if set(manifest['files'])!=expected:raise ValueError()
        for name,checksum in manifest['files'].items():
            if not re.fullmatch(r'database\.dump|content-[0-9]+\.bundle',name):raise ValueError()
            path=directory/name
            if path.is_symlink() or not path.is_file() or digest(path)!=checksum:raise ValueError()
        with tempfile.TemporaryDirectory(prefix='grow-bundle-check-') as tmp:
            command(['git','init','--bare',tmp])
            for item in manifest['repositories'].values():
                command(['git','--git-dir',tmp,'bundle','verify',str((directory/item['bundle']).resolve())])
        return manifest
    except (OSError,ValueError,KeyError,TypeError):raise BackupError('备份包清单或校验失败。') from None


def restore(dsn, directory, content_directory, *, env=None, writers_stopped=False):
    env=os.environ if env is None else env
    if not writers_stopped:raise BackupError('恢复前必须停止全部写入。')
    manifest=verify(directory);directory=Path(directory).resolve();content_directory=Path(content_directory).absolute()
    if content_directory.exists():raise BackupError('内容恢复目录已存在；请使用新的目录。')
    if fingerprint(env.get('ACCOUNT_ENCRYPTION_KEY'))!=manifest['encryption_key_sha256']:raise BackupError('必须提供备份时的 ACCOUNT_ENCRYPTION_KEY。')
    configured={'repository':env.get('GITHUB_CONTENT_REPO',''),'branch':env.get('GITHUB_CONTENT_BRANCH','main')}
    if configured!=manifest['default_content']:raise BackupError('恢复配置的默认内容仓库/分支与备份不一致。')
    subprocess_env=pg_env(dsn)
    with psycopg2.connect(dsn,connect_timeout=10) as connection:
        cur=connection.cursor();cur.execute("SELECT count(*) FROM pg_namespace WHERE nspname NOT IN ('public','pg_catalog','information_schema') AND nspname NOT LIKE 'pg_toast%%' AND nspname NOT LIKE 'pg_temp%%'")
        namespaces=cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'")
        if namespaces or cur.fetchone()[0]:raise BackupError('恢复仅允许空数据库，拒绝覆盖现有数据。')
    # Validate Git data before touching PostgreSQL. Never push or alter a remote branch.
    content_directory.mkdir(mode=0o700)
    for index,item in enumerate(manifest['repositories'].values()):
        mirror=content_directory/('content-'+str(index)+'.git')
        command(['git','clone','--mirror',str(directory/item['bundle']),str(mirror)])
        command(['git','--git-dir',str(mirror),'fsck','--full'])
        for sha in item['commits']:command(['git','--git-dir',str(mirror),'cat-file','-e',sha+'^{commit}'])
    command(['pg_restore','--single-transaction','--exit-on-error','--no-owner','--no-acl','--dbname='+subprocess_env['PGDATABASE'],str(directory/'database.dump')],subprocess_env)
    with psycopg2.connect(dsn,connect_timeout=10) as connection:actual=inventory(connection,env)
    if actual['tables']!=manifest['tables'] or actual['row_hashes']!=manifest['row_hashes']:raise BackupError('恢复后数据核对未通过；不要启动写入，请保留现场检查。')
    return {'ok':True,'tables':len(actual['tables']),'repositories':len(manifest['repositories'])}


def main():
    from run_local import load_environment
    load_environment(Path(__file__).resolve().parent)
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('create','verify','restore'))
    parser.add_argument('directory');parser.add_argument('--content-mirror',action='append',default=[],metavar='OWNER/REPO=/ABS/PATH.git')
    parser.add_argument('--content-directory');parser.add_argument('--writers-stopped',action='store_true');args=parser.parse_args()
    try:
        if args.command=='verify':result={'ok':True,'tables':len(verify(args.directory)['tables'])}
        elif args.command=='create':
            mirrors=dict(v.split('=',1) for v in args.content_mirror)
            manifest=create(os.environ['DATABASE_URL'],args.directory,mirrors,writers_stopped=args.writers_stopped)
            result={'ok':True,'tables':len(manifest['tables']),'repositories':len(manifest['repositories'])}
        else:
            if not args.content_directory:raise BackupError('restore 需要 --content-directory。')
            result=restore(os.environ['DATABASE_URL'],args.directory,args.content_directory,writers_stopped=args.writers_stopped)
        print(json.dumps(result));return 0
    except BackupError as error:
        print(str(error),file=__import__('sys').stderr);return 2
    except (psycopg2.Error,KeyError,ValueError,OSError):
        # Never echo libpq stderr, credentials, private rows or raw configuration.
        print('备份/恢复未完成；请核对配置、停写确认、目标为空、密钥、内容镜像和工具版本。',file=__import__('sys').stderr);return 2


if __name__=='__main__':raise SystemExit(main())

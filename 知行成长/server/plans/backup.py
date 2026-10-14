"""Full local learning snapshot; restoration is an explicit offline operation."""
import argparse
import json
import os
import shutil
import sqlite3
import tempfile
import uuid
from pathlib import Path
from contextlib import closing, contextmanager
import fcntl
from copilot.core import encoded, digest, fail, now
from .store import Plans

ROOTS=('认知阅读','学习计划','每日认知与通识学习','英文阅读','结构化表达','现代思维工具教程','深度写作','执行复盘','整合练习','热门与深度文章')
EXTENSIONS={'.md','.json','.png','.jpg','.jpeg','.webp','.pdf'}


def safe(root,rel):
    if Path(rel).is_absolute() or '..' in Path(rel).parts or Path(rel).parts[0] not in ROOTS:
        fail('conflict','备份路径无效。')
    p=root/rel
    for part in (p,*p.parents):
        if part.is_symlink():fail('conflict','备份内容不能经过符号链接。')
        if part==root:break
    if not p.resolve().is_relative_to(root.resolve()):fail('conflict','备份路径越界。')
    return p


def inventory(store):
    files={}
    for name in ROOTS:
        folder=store.root/name
        if folder.is_symlink():fail('conflict','模块目录不能是符号链接。')
        if not folder.exists():continue
        for p in folder.rglob('*'):
            if p.is_symlink():fail('conflict','备份发现符号链接，请先核对。')
            if p.is_file() and p.suffix.lower() in EXTENSIONS:
                rel=str(p.relative_to(store.root));files[rel]=digest(safe(store.root,rel).read_bytes())
    return files


@contextmanager
def legacy_lock(store):
    path=store.db.parent/'.copilot';path.mkdir(exist_ok=True)
    with (path/'renzhi.lock').open('a') as f:
        fcntl.flock(f,fcntl.LOCK_EX)
        try:yield
        finally:fcntl.flock(f,fcntl.LOCK_UN)


def database_snapshot(store, target):
    with store.conn() as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst)
        # The existing settings UI can store an API key in SQLite. Do not export it.
        if dst.execute("SELECT 1 FROM sqlite_master WHERE name='copilot_settings'").fetchone():
            dst.execute('PRAGMA secure_delete=ON')
            dst.execute("DELETE FROM copilot_settings WHERE key='api_key'")
            dst.commit()
            dst.execute('VACUUM')


def snapshot(store):
    # Caller holds the new-plan lock and has stopped uncoordinated external writers.
    with legacy_lock(store):
        files=inventory(store);folder=store.runtime/'backups'/uuid.uuid4().hex
        folder.mkdir(parents=True)
        try:
            for rel in files:
                target=folder/'files'/rel;target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(safe(store.root,rel),target)
                if digest(target.read_bytes())!=files[rel]:fail('conflict','备份期间内容变化。')
            database_snapshot(store, folder/'data.db')
            if inventory(store)!=files:fail('conflict','备份期间发现外部写入。')
            manifest={'version':1,'created_at':now(),'files':files,'database_hash':digest((folder/'data.db').read_bytes())}
            (folder/'manifest.json').write_text(encoded(manifest))
            return {'path':str(folder),'files':len(files),'scope':'学习模块资料与整份平台数据库；不含密钥'}
        except BaseException:
            shutil.rmtree(folder);raise


def validate(folder):
    folder=Path(folder).resolve();m=json.loads((folder/'manifest.json').read_text())
    if m.get('version')!=1:fail('conflict','备份版本不支持。')
    for rel,h in m['files'].items():
        if digest(safe(folder/'files',rel).read_bytes())!=h:fail('conflict','备份文件损坏。')
    if (folder/'data.db').is_symlink() or digest((folder/'data.db').read_bytes())!=m['database_hash']:fail('conflict','备份数据库损坏。')
    with closing(sqlite3.connect(f'file:{folder/"data.db"}?mode=ro',uri=True)) as c:
        if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':fail('conflict','数据库完整性检查失败。')
    return folder,m


def preview(store,folder):
    folder,m=validate(folder);current=inventory(store)
    with store.conn() as c:db_hash=digest('\n'.join(c.iterdump()))
    return {'token':digest(encoded({'current':current,'db':db_hash,'target':m})),
            'changes':[p for p in sorted(set(current)|set(m['files'])) if current.get(p)!=m['files'].get(p)],
            'warning':'将恢复整份平台数据库，包含旧模块、待办与复盘记录；先保存当前完整备份。'}


def restore(store,folder,token):
    with store.lock():
        if preview(store,folder)['token']!=token:fail('conflict','预览后数据已变化，请重新预览。')
        folder,m=validate(folder);journal=store.runtime/'restore-pending.json'
        if journal.exists():fail('conflict','存在未完成恢复，先检查日志。')
        before=snapshot(store)
        journal.write_text(encoded({'before':before,'target':str(folder),'created_at':now()}))
        with legacy_lock(store):
            for rel in sorted(set(inventory(store))|set(m['files'])):
                p=safe(store.root,rel)
                if rel not in m['files']:p.unlink();continue
                p.parent.mkdir(parents=True,exist_ok=True)
                fd,tmp=tempfile.mkstemp(dir=p.parent,prefix='.restore-')
                try:
                    with os.fdopen(fd,'wb') as f:
                        f.write(safe(folder/'files',rel).read_bytes());f.flush();os.fsync(f.fileno())
                    os.replace(tmp,p)
                finally:
                    if os.path.exists(tmp):os.unlink(tmp)
            with closing(sqlite3.connect(folder/'data.db')) as src,store.conn() as dst:src.backup(dst)
        journal.unlink()
        return {'restored':str(folder),'before':before}


def main():
    parser=argparse.ArgumentParser(description='停服务和外部写入后预览或恢复完整平台备份。')
    parser.add_argument('folder');parser.add_argument('--confirm-token');parser.add_argument('--writers-stopped',action='store_true')
    args=parser.parse_args();server=Path(__file__).resolve().parents[1];store=Plans(server.parents[1],server/'data.db')
    if args.confirm_token and not args.writers_stopped:parser.error('恢复须显式传入--writers-stopped并已停止所有写入')
    result=restore(store,args.folder,args.confirm_token) if args.confirm_token else preview(store,args.folder)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()

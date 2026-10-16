"""Versioned personal-asset backups; restoration is an explicit offline operation."""
import argparse
import json
import os
import shutil
import db
import tempfile
import uuid
from pathlib import Path
from contextlib import closing, contextmanager
import fcntl
from copilot.core import encoded, digest, fail, now
from .store import Plans

# These are fixed versioned contracts. Future scope changes need a new version.
ROOTS = ('认知阅读', '学习计划', '每日认知与通识学习', '英文阅读', '结构化表达',
         '现代思维工具教程', '深度写作', '执行复盘', '整合练习', '热门与深度文章')
LEGACY_EXTENSIONS = frozenset({'.md', '.json', '.png', '.jpg', '.jpeg', '.webp', '.pdf'})
EXTENSIONS = LEGACY_EXTENSIONS | {'.gif', '.svg', '.txt', '.csv', '.tsv',
                                  '.mp3', '.m4a', '.wav', '.ogg', '.mp4', '.webm',
                                  '.heic', '.docx', '.xlsx', '.pptx'}
ROOT_DOCUMENTS = frozenset({
    'README.md', '记录分工指南.md', '知识索引.md', '学习系统总览.md',
    '现代思维工具系统学习教程.md', '现代思维工具学习规划与教程.md',
    '高认知能力训练规划.md', '长期成长学习体系总规划.md',
})
PLATFORM_DOCUMENTS = frozenset('知行成长/' + name for name in (
    'README.md', '内容存储规则.md', '平台演进规划.md', '数据边界与备份规则.md',
    'P0实施任务.md', 'P0验收结果.md',
))
EXACT_FILES = ROOT_DOCUMENTS | PLATFORM_DOCUMENTS
SENSITIVE_EXTENSIONS = {'.pem', '.key', '.p12', '.pfx', '.sqlite', '.db'}
FORMAT_VERSION = 2


def allowed(relative, version):
    if not isinstance(relative, str) or not relative or version not in (1, 2):
        return False
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts or path.as_posix() != relative:
        return False
    if version == 2 and relative in EXACT_FILES:
        return True
    if len(path.parts) < 2 or path.parts[0] not in ROOTS:
        return False
    if version == 1:
        return path.suffix.lower() in LEGACY_EXTENSIONS
    if any(p.startswith('.') for p in path.parts[1:]):
        return False
    return path.suffix.lower() in EXTENSIONS


def safe(root, rel, version=FORMAT_VERSION):
    if not allowed(rel, version):
        fail('conflict', '备份路径不属于该版本的资产范围。')
    root = Path(root)
    p = root / rel
    for part in (p, *p.parents):
        if part.is_symlink():
            fail('conflict', '备份内容不能经过符号链接。')
        if part == root:
            break
    if not p.resolve().is_relative_to(root.resolve()):
        fail('conflict', '备份路径越界。')
    return p


def inventory_report(store, version=FORMAT_VERSION):
    if version not in (1, 2):
        fail('conflict', '备份版本不支持。')
    files, excluded = {}, []

    def inspect(p):
        rel = p.relative_to(store.root).as_posix()
        if p.is_symlink():
            fail('conflict', '备份范围内发现符号链接：' + rel)
        if not p.is_file():
            fail('conflict', '登记的资料路径不是普通文件：' + rel)
        if allowed(rel, version):
            files[rel] = digest(safe(store.root, rel, version).read_bytes())
        else:
            reason = '未支持的文件类型'
            if p.name.startswith('.') or p.suffix.lower() in SENSITIVE_EXTENSIONS:
                reason = '敏感或隐藏文件；不自动收集'
            excluded.append({'path': rel, 'reason': reason})

    for name in ROOTS:
        folder = store.root / name
        if folder.is_symlink():
            fail('conflict', '模块目录不能是符号链接。')
        if not folder.exists():
            continue
        if not folder.is_dir():
            fail('conflict', '模块路径不是目录：' + name)
        def unreadable(exc):
            fail('conflict', '无法完整读取备份目录：' + str(exc.filename or folder))

        for current, dirs, names in os.walk(folder, followlinks=False, onerror=unreadable):
            for name in sorted(dirs.copy()):
                p = Path(current) / name
                if p.is_symlink():
                    fail('conflict', '备份范围内发现符号链接。')
                if version == 2 and name.startswith('.'):
                    dirs.remove(name)
                    excluded.append({'path': p.relative_to(store.root).as_posix(),
                                     'reason': '隐藏目录；未遍历其内容'})
            for name in sorted(names):
                inspect(Path(current) / name)
    if version == 2:
        for rel in sorted(EXACT_FILES):
            p = store.root / rel
            if p.exists() or p.is_symlink():
                inspect(safe(store.root, rel, version))
        for p in sorted(store.root.iterdir()):
            if p.name in ROOTS or p.name in ROOT_DOCUMENTS:
                continue
            if p.name == '知行成长' and p.is_dir() and not p.is_symlink():
                for child in sorted(p.iterdir()):
                    rel = child.relative_to(store.root).as_posix()
                    if rel not in PLATFORM_DOCUMENTS:
                        excluded.append({'path': rel, 'reason': '程序、运行资料或未登记文档；目录未遍历'})
            else:
                excluded.append({'path': p.name, 'reason': '不在资产白名单；目录未遍历'})
    return {'files': dict(sorted(files.items())),
            'excluded': sorted(excluded, key=lambda x: x['path'])}


def inventory(store, version=FORMAT_VERSION):
    return inventory_report(store, version)['files']


@contextmanager
def legacy_lock(store):
    path = store.db.parent / '.copilot'
    path.mkdir(exist_ok=True)
    with (path / 'renzhi.lock').open('a') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def database_snapshot(store, target):
    with store.conn() as src, closing(db.connect()) as dst:
        src.backup(dst)
        # Redact the known credential field only; personal contents remain private.
        if dst.execute("SELECT 1 FROM sqlite_master WHERE name='copilot_settings'").fetchone():
            dst.execute('PRAGMA secure_delete=ON')
            dst.execute("DELETE FROM copilot_settings WHERE key='api_key'")
            dst.commit()
            dst.execute('VACUUM')


def snapshot(store):
    # Caller holds the plan lock and has stopped uncoordinated external writers.
    with legacy_lock(store):
        report = inventory_report(store)
        files = report['files']
        folder = store.runtime / 'backups' / uuid.uuid4().hex
        folder.mkdir(parents=True)
        try:
            for rel in files:
                target = folder / 'files' / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(safe(store.root, rel), target)
                if digest(target.read_bytes()) != files[rel]:
                    fail('conflict', '备份期间内容变化。')
            database_snapshot(store, folder / 'data.db')
            if inventory_report(store) != report:
                fail('conflict', '备份期间发现外部写入或资产范围变化。')
            manifest = {'version': FORMAT_VERSION, 'created_at': now(), **report,
                        'database_hash': digest((folder / 'data.db').read_bytes()),
                        'database_scope': '整份平台数据库；移除copilot_settings.api_key，其他个人内容仍需保密'}
            (folder / 'manifest.json').write_text(encoded(manifest), encoding='utf-8')
            return {'path': str(folder), 'files': len(files), 'version': FORMAT_VERSION,
                    'excluded': report['excluded'],
                    'scope': '登记的个人资料、平台规则及整份平台数据库；详见manifest.json'}
        except BaseException:
            shutil.rmtree(folder)
            raise


def validate(folder):
    folder = Path(folder).resolve()
    try:
        manifest_path = folder / 'manifest.json'
        if manifest_path.is_symlink():
            fail('conflict', '备份清单不能是符号链接。')
        m = json.loads(manifest_path.read_text(encoding='utf-8'))
        if not isinstance(m, dict) or type(m.get('version')) is not int or m['version'] not in (1, 2):
            fail('conflict', '备份版本不支持。')
        if not isinstance(m.get('files'), dict):
            fail('conflict', '备份文件清单无效。')
        for rel, h in m['files'].items():
            if digest(safe(folder / 'files', rel, m['version']).read_bytes()) != h:
                fail('conflict', '备份文件损坏。')
        db = folder / 'data.db'
        if db.is_symlink() or digest(db.read_bytes()) != m.get('database_hash'):
            fail('conflict', '备份数据库损坏。')
        with closing(db.connect() + '?mode=ro', uri=True)) as c:
            if c.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                fail('conflict', '数据库完整性检查失败。')
    except (OSError, ValueError, db.Error) as exc:
        fail('conflict', '备份不完整或无法读取：' + type(exc).__name__)
    return folder, m


def preview(store, folder):
    folder, m = validate(folder)
    report = inventory_report(store, m['version'])
    current = report['files']
    with store.conn() as c:
        db_hash = digest('\n'.join(c.iterdump()))
        current_tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    with closing(db.connect().as_uri() + '?mode=ro', uri=True)) as c:
        target_tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return {'token': digest(encoded({'current': current, 'db': db_hash, 'target': m})),
            'version': m['version'], 'excluded': report['excluded'],
            'backup_excluded': m.get('excluded', []),
            'changes': [p for p in sorted(set(current) | set(m['files']))
                        if current.get(p) != m['files'].get(p)],
            'database_tables_removed': sorted(current_tables - target_tables),
            'warning': '将恢复整份平台数据库，可能回退或移除后来新增的记录与表；文件仅按备份版本范围恢复。先停止服务与所有外部写入。'}


def restore(store, folder, token):
    with store.lock():
        journal = store.runtime / 'restore-pending.json'
        if journal.exists():
            fail('conflict', '存在未完成恢复，先检查日志。')
        if preview(store, folder)['token'] != token:
            fail('conflict', '预览后数据已变化，请重新预览。')
        folder, m = validate(folder)
        before = snapshot(store)
        journal.write_text(encoded({'before': before, 'target': str(folder),
                                    'created_at': now()}), encoding='utf-8')
        with legacy_lock(store):
            current = inventory(store, m['version'])
            for rel in sorted(set(current) | set(m['files'])):
                p = safe(store.root, rel, m['version'])
                if rel not in m['files']:
                    p.unlink()
                    continue
                p.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp = tempfile.mkstemp(dir=p.parent, prefix='.restore-')
                try:
                    with os.fdopen(fd, 'wb') as f:
                        f.write(safe(folder / 'files', rel, m['version']).read_bytes())
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp, p)
                finally:
                    if os.path.exists(tmp):
                        os.unlink(tmp)
            with closing(db.connect()) as src, store.conn() as dst:
                src.backup(dst)
        journal.unlink()
        return {'restored': str(folder), 'before': before}


def main():
    parser = argparse.ArgumentParser(description='停服务和外部写入后预览或恢复完整平台备份。')
    parser.add_argument('folder')
    parser.add_argument('--confirm-token')
    parser.add_argument('--writers-stopped', action='store_true')
    args = parser.parse_args()
    server = Path(__file__).resolve().parents[1]
    store = Plans(server.parents[1], server / 'data.db')
    if args.confirm_token and not args.writers_stopped:
        parser.error('恢复须显式传入--writers-stopped并已停止所有写入')
    result = restore(store, args.folder, args.confirm_token) if args.confirm_token else preview(store, args.folder)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

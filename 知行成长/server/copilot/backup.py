"""Consistent backups and an offline, preview-first restore command."""
import argparse
import json
import os
import shutil
import db
import tempfile
import uuid
from pathlib import Path
from contextlib import closing

from .core import MODULE, Store, digest, encoded, fail, now


def inventory(store):
    store.workspace()
    result = {}
    for p in sorted(store.module.rglob('*')):
        if p.suffix not in ('.md', '.json'):
            continue
        relative = str(p.relative_to(store.module))
        p = store.path(relative)
        if p.is_file():
            result[relative] = digest(p.read_bytes())
    return result


def snapshot(store, label='manual'):
    """Caller holds the shared writer lock and has coordinated external writers."""
    files = inventory(store)
    folder = store.runtime / 'backups' / f'{label}-{uuid.uuid4().hex}'
    folder.mkdir(parents=True)
    try:
        for relative in files:
            destination = folder / 'files' / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(store.path(relative), destination)
            if digest(destination.read_bytes()) != files[relative]:
                fail('conflict', '备份期间资料发生变化，请重试。')
        with closing(db.connect()) as src, closing(db.connect()) as dst:
            src.backup(dst)
        if inventory(store) != files:
            fail('conflict', '备份期间发现外部写入，请重新协调后重试。')
        manifest = {'version': 1, 'created_at': now(), 'files': files,
                    'database_hash': digest((folder / 'data.db').read_bytes())}
        (folder / 'manifest.json').write_text(encoded(manifest), encoding='utf-8')
        return {'backup_id': folder.name, 'path': str(folder), 'files': len(files)}
    except BaseException:
        shutil.rmtree(folder)
        raise


def validated_backup(folder):
    folder = Path(folder).resolve()
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('version') != 1:
        fail('conflict', '不支持的备份版本。')
    for relative, h in manifest['files'].items():
        p = folder / 'files' / relative
        if (not p.resolve().is_relative_to(folder / 'files') or p.is_symlink()
                or p.suffix not in ('.md', '.json') or digest(p.read_bytes()) != h):
            fail('conflict', '备份文件校验失败。')
    if digest((folder / 'data.db').read_bytes()) != manifest['database_hash']:
        fail('conflict', '备份数据库校验失败。')
    with closing(db.connect()) as c:
        if c.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            fail('conflict', '备份数据库完整性检查失败。')
    return folder, manifest


def restore_preview(store, folder):
    folder, manifest = validated_backup(folder)
    current = inventory(store)
    target = manifest['files']
    diff = [{'path': p, 'action': 'remove' if p not in target else 'create' if p not in current else 'replace'}
            for p in sorted(set(current) | set(target)) if current.get(p) != target.get(p)]
    # Includes DB state: restoring must not silently discard edits made after preview.
    with closing(db.connect()) as c:
        db_state = digest('\n'.join(c.iterdump()))
    token = digest(encoded({'files': current, 'database': db_state, 'target': manifest}))
    return {'preview_token': token, 'changes': diff, 'database': '将恢复整份知行成长平台数据库；当前状态先完整备份'}


def restore(store, folder, token):
    with store.lock():
        preview = restore_preview(store, folder)
        if preview['preview_token'] != token:
            fail('conflict', '当前数据已变化，请重新预览。')
        folder, manifest = validated_backup(folder)
        before = snapshot(store, 'before-restore')
        journal = store.runtime / 'restore-pending.json'
        if journal.exists():
            fail('conflict', '存在未完成恢复，请先检查restore-pending.json及其中的原始备份。')
        journal.write_text(encoded({'target': str(folder), 'before': before, 'started_at': now()}), encoding='utf-8')
        for relative in sorted(set(inventory(store)) | set(manifest['files'])):
            target = store.path(relative)
            if relative not in manifest['files']:
                target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temp = tempfile.mkstemp(prefix='.restore-', dir=target.parent)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write((folder / 'files' / relative).read_bytes())
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp, target)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
        with closing(db.connect()) as src, closing(db.connect()) as dst:
            src.backup(dst)
        journal.unlink()
        return {'restored': str(folder), 'previous_backup': before}


def main():
    parser = argparse.ArgumentParser(description='停止服务和外部写入后，预览并恢复学习备份。')
    parser.add_argument('backup')
    parser.add_argument('--confirm-token')
    parser.add_argument('--writers-stopped', action='store_true')
    args = parser.parse_args()
    server = Path(__file__).resolve().parents[1]
    store = Store(server.parents[1], server / 'data.db')
    if args.confirm_token:
        if not args.writers_stopped:
            parser.error('正式恢复须先停止知行成长平台和自动写入，再明确传入--writers-stopped')
        result = restore(store, args.backup, args.confirm_token)
    else:
        result = restore_preview(store, args.backup)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

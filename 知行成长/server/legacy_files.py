"""Explicit, hash-bound file imports. Source files are never changed or deleted."""
import argparse
import json
from pathlib import Path

from cloud_content import ROOTS, is_formal, valid_path
from copilot.core import digest, encoded, fail, now


def source_files(root,modules=ROOTS):
    root=Path(root).absolute();result={}
    if root.is_symlink():fail('migration_source','迁移根目录不能是符号链接。')
    for module in modules:
        base=root/module
        if not base.exists():continue
        if base.is_symlink() or not base.is_dir():fail('migration_source','来源模块目录不可用。')
        for file in sorted(base.rglob('*')):
            relative=str(file.relative_to(root))
            if any(part.startswith('.') for part in file.relative_to(root).parts):continue
            if file.is_symlink() or not file.resolve().is_relative_to(root.resolve()):fail('migration_source','来源包含符号链接或越界路径：'+relative)
            if not file.is_file() or file.suffix.lower() not in ('.md','.json'):continue
            if file.stat().st_size>1_000_000:fail('migration_source','来源文件超出 1 MB 限制：'+relative)
            try:text=file.read_text(encoding='utf-8')
            except (OSError,UnicodeError):fail('migration_source','来源文件不可读取或不是 UTF-8：'+relative)
            valid_path(relative);result[relative]=text
    return result


def preview(documents,root,modules=ROOTS,files=None):
    files=source_files(root,modules) if files is None else files
    head=documents.content.head()
    current={path:documents.hash(path) for path in files}
    pending={};conflicts=[]
    for path,text in files.items():
        target=current[path];wanted=digest(text)
        if target not in (None,wanted):
            # Initial empty course catalog is private setup data, never personal content.
            seed='# 学习记录\n\n| 课次 | 日期 | 课程 | 资料 | 状态 |\n|---|---|---|---|---|\n'
            if not (path.endswith('/学习记录.md') and target==digest(seed)):
                conflicts.append({'path':path,'reason':'数据库中已有不同版本；保留双方，需先核对。'})
        if is_formal(path):
            existing=documents.content.read_text(path,head,missing=True) if head else None
            if existing is not None and digest(existing) not in (wanted,target):conflicts.append({'path':path,'reason':'GitHub 中已有不同版本，不能覆盖。'})
        if target!=wanted:pending[path]=text
    # Bind to record state too: no file mirror may replace a newer personal record.
    with documents.store.conn() as c:
        reading=[dict(r) for r in c.execute('SELECT id,data FROM reading_records ORDER BY id')]
    material={'source_root':str(Path(root).resolve()),'files':{p:digest(t) for p,t in files.items()},'current':current,'head':head,'reading':reading,
              'binding':documents.get('cloud_content_settings','binding')}
    return {'token':digest(encoded(material)),'files':len(files),'formal_markdown':sum(is_formal(p) for p in files),
            'private_documents':sum(not is_formal(p) for p in files),'changed':len(pending),'conflicts':conflicts,
            'source_hashes':material['files']}


def apply(documents,root,token,modules=ROOTS):
    with documents.lock():
        key='file-import:'+token
        existing=documents.get('cloud_publications',key)
        if existing:
            if existing['state']!='done':documents.finish(key,existing)
            return existing['result']
        files=source_files(root,modules)
        report=preview(documents,root,modules,files)
        if report['token']!=token:fail('migration_changed','预览后来源、记录或 GitHub 分支已变化，请重新预览。')
        if report['conflicts']:fail('migration_conflict','发现已有不同版本，原数据保留，请核对迁移预览。')
        sql=[];stamp=now()
        for path,text in files.items():
            identity=digest(str(Path(root).resolve())+':'+path+':'+digest(text))
            record={'path':path,'source_hash':digest(text),'source_root':str(Path(root).resolve()),
                    'imported_at':stamp,'storage':'github' if is_formal(path) else 'database'}
            if not is_formal(path):record['original_text']=text
            sql.append(('INSERT INTO cloud_file_imports VALUES (?,?) ON CONFLICT(id) DO NOTHING',[identity,encoded(record)]))
        articles=0
        for path,text in files.items():
            if not path.startswith('认知阅读/文章资料/') or not path.endswith('/文章信息.json'):continue
            aid=path.split('/')[2]
            try:data=json.loads(text)
            except ValueError:fail('migration_invalid','文章信息不是有效 JSON：'+path)
            if not isinstance(data,dict) or data.get('id')!=aid or data.get('type')!='article':fail('migration_invalid','文章信息与目录不一致：'+path)
            old=documents.get('reading_records',aid)
            if old and old.get('type')!='article':fail('migration_conflict','文章编号已用于其他数据。')
            data={**data,**(old or {})}
            from reading.cloud_store import validate_article_source
            validate_article_source(data,aid)
            base='认知阅读/文章资料/'+aid+'/'
            data['hashes']={**data.get('hashes',{}),**{p:digest(t) for p,t in files.items() if p.startswith(base)}}
            if base+'中文导读.md' in files:data['guide']=files[base+'中文导读.md']
            for field in ('read','read_later','bookmarked','archived'):data.setdefault(field,False)
            data.setdefault('author','未知');data.setdefault('language','zh');data.setdefault('summary','')
            sql.append(('INSERT INTO reading_records VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',[aid,encoded(data)]))
            articles+=1
        # Keep existing preferences; attach their private document hash to the import.
        pref_path='认知阅读/阅读偏好.md'
        if pref_path in files:
            preferences=documents.get('reading_records','preferences')
            if preferences:
                preferences['hash']=digest(files[pref_path])
                sql.append(('UPDATE reading_records SET data=? WHERE id=?',[encoded(preferences),'preferences']))
        changed={p:text for p,text in files.items() if documents.hash(p)!=digest(text)}
        result={k:v for k,v in report.items() if k not in ('source_hashes','token','conflicts')}
        result.update(id=key,source_preserved=True,articles=articles)
        documents.publish(key,{'import':token},changed,sql,result,
                          expected={p:documents.hash(p) for p in changed},adopt_existing=True)
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--apply-token')
    args=parser.parse_args()
    from copilot.cloud_store import CloudStore
    import os
    store=CloudStore(args.root,Path(os.getenv('RUNTIME_ROOT','/tmp/learning-migration-runtime')))
    store.initialize()
    report=apply(store.documents,args.root,args.apply_token) if args.apply_token else preview(store.documents,args.root)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()

"""Export the public teaching whitelist for a new, independent installation."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

PATTERNS=('英文阅读/每日文章/*.md','结构化表达/每日练习/*.md','现代思维工具教程/*.md')

class MaterialError(ValueError):pass


def prepare(source,destination):
    source=Path(source).resolve();destination=Path(destination).absolute()
    if destination.exists():raise MaterialError('资料目标已存在，请选择新目录，避免覆盖既有资料。')
    files=sorted({file for pattern in PATTERNS for file in source.glob(pattern)})
    if not files:raise MaterialError('未找到发行教材，请核对源码中的内置教材目录。')
    for file in files:
        if file.is_symlink() or not file.is_file() or not file.resolve().is_relative_to(source):
            raise MaterialError('发行教材包含链接或越界文件，已停止导出。')
    staging=Path(tempfile.mkdtemp(prefix='.grow-materials-',dir=destination.parent))
    try:
        manifest={'version':1,'files':{}}
        for file in files:
            relative=file.relative_to(source);target=staging/relative;target.parent.mkdir(parents=True,exist_ok=True)
            body=file.read_bytes();target.write_bytes(body)
            manifest['files'][relative.as_posix()]=hashlib.sha256(body).hexdigest()
        (staging/'materials-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        staging.rename(destination)
        return {'copied_files':len(files),'ok':True}
    finally:
        if staging.exists():shutil.rmtree(staging)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination');parser.add_argument('--source',default=str(Path(__file__).resolve().parent.parent/'学习资料'))
    args=parser.parse_args()
    try:print(json.dumps(prepare(args.source,args.destination)));return 0
    except (MaterialError,OSError):
        print('教材导出失败；请核对源目录、目标不存在且父目录可写、文件无链接。',file=__import__('sys').stderr);return 2


if __name__=='__main__':raise SystemExit(main())

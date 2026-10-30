"""Private immutable archive files. All descendants are opened relative to checked FDs."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import uuid

LIMIT=100_000_000
NAME=re.compile(r'^[a-z][a-z0-9_]*\.(?:json|jsonl\.gz|csv)$')


class ArchiveFileError(ValueError):
    pass


def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
def checksum(value):return hashlib.sha256(value).hexdigest()


class ArchiveFiles:
    def __init__(self,root):
        self.root=Path(root)
        if not self.root.is_absolute() or self.root.name in ('','.', '..'):raise ArchiveFileError('归档根目录须为独立绝对路径。')

    @staticmethod
    def key(key):
        if len(key)!=5 or any(not re.fullmatch(r'[a-z0-9-]{1,100}',p) or p in ('.','..') for p in key):raise ArchiveFileError('归档身份无效。')
        return tuple(key)

    @staticmethod
    def directory(parent,name,create):
        if create:
            try:os.mkdir(name,0o700,dir_fd=parent)
            except FileExistsError:pass
        fd=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
        if create:os.fchmod(fd,0o700)
        return fd

    def root_fd(self,create):
        # macOS exposes these fixed system aliases. No arbitrary ancestor link
        # is resolved; all other components are walked with O_NOFOLLOW.
        parts=self.root.parts[1:]
        if sys.platform=='darwin' and parts and parts[0] in ('tmp','var','etc'):
            alias='/'+parts[0]
            if os.path.islink(alias) and os.readlink(alias) in ('private/'+parts[0],'/private/'+parts[0]):parts=('private',*parts)
        fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
        try:
            for part in parts[:-1]:
                if create:
                    try:os.mkdir(part,0o700,dir_fd=fd)
                    except FileExistsError:pass
                child=self.directory(fd,part,False);os.close(fd);fd=child
            return self.directory(fd,parts[-1],create)
        finally:os.close(fd)

    def parent_fd(self,key,create):
        fd=self.root_fd(create)
        try:
            for part in self.key(key)[:-1]:
                child=self.directory(fd,part,create);os.close(fd);fd=child
            return fd
        except BaseException:os.close(fd);raise

    @staticmethod
    def read_file(fd,name,maximum):
        handle=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
        try:
            info=os.fstat(handle)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>maximum:raise ArchiveFileError('归档文件类型或大小无效。')
            chunks=[];size=0
            while True:
                chunk=os.read(handle,min(1024*1024,maximum+1-size))
                if not chunk:break
                size+=len(chunk)
                if size>maximum:raise ArchiveFileError('归档超过读取限制。')
                chunks.append(chunk)
            return b''.join(chunks)
        finally:os.close(handle)

    @staticmethod
    def put_file(fd,name,data):
        handle=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
        try:
            with os.fdopen(handle,'wb',closefd=False) as stream:stream.write(data);stream.flush();os.fsync(handle)
        finally:os.close(handle)

    def read_at(self,parent,leaf,expected_hash=None):
        fd=self.directory(parent,leaf,False)
        try:
            raw=self.read_file(fd,'manifest.json',128_000)
            if expected_hash is not None and checksum(raw)!=expected_hash:raise ArchiveFileError('归档清单哈希不匹配。')
            manifest=json.loads(raw)
            if manifest.get('format')!='grow-research-archive-v1' or not isinstance(manifest.get('files'),dict) or not 1<=len(manifest['files'])<=24:raise ArchiveFileError('归档清单无效。')
            if set(os.listdir(fd))!={'manifest.json',*manifest['files']}:raise ArchiveFileError('归档文件清单不一致。')
            files={};total=0
            for name,item in manifest['files'].items():
                if not NAME.fullmatch(name) or name=='manifest.json' or not isinstance(item,dict) or type(item.get('size')) is not int or not 0<=item['size']<=LIMIT:raise ArchiveFileError('归档文件描述无效。')
                data=self.read_file(fd,name,item['size']);total+=len(data)
                if total>LIMIT or len(data)!=item['size'] or checksum(data)!=item.get('sha256'):raise ArchiveFileError('归档文件校验失败。')
                files[name]=data
            return manifest,files,checksum(raw)
        finally:os.close(fd)

    def read(self,key,expected_hash=None):
        parent=None
        try:
            self.key(key);parent=self.parent_fd(key,False)
            manifest,files,_=self.read_at(parent,key[-1],expected_hash);return manifest,files
        except (OSError,ValueError,KeyError,TypeError) as error:
            raise ArchiveFileError('归档缺失、损坏或路径不安全；原资料保留。') from error
        finally:
            if parent is not None:os.close(parent)

    def write(self,key,metadata,files):
        parent=lock=stage_fd=None;temporary=None
        try:
            self.key(key)
            if not 1<=len(files)<=24 or any(not NAME.fullmatch(name) or name=='manifest.json' or not isinstance(data,bytes) for name,data in files.items()) or sum(map(len,files.values()))>LIMIT:raise ArchiveFileError('归档产物无效或超过100MB。')
            manifest={'format':'grow-research-archive-v1',**metadata,'files':{name:{'size':len(data),'sha256':checksum(data)} for name,data in sorted(files.items())}}
            raw=canonical(manifest)
            if len(raw)>128_000:raise ArchiveFileError('归档清单过大。')
            parent=self.parent_fd(key,True)
            lock=os.open('.archive.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600,dir_fd=parent)
            info=os.fstat(lock)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise ArchiveFileError('归档锁文件类型无效。')
            fcntl.flock(lock,fcntl.LOCK_EX)
            try:existing=os.stat(key[-1],dir_fd=parent,follow_symlinks=False)
            except FileNotFoundError:existing=None
            if existing is not None:
                saved,_,digest=self.read_at(parent,key[-1])
                if saved!=manifest:raise ArchiveFileError('同一归档身份内容冲突，未覆盖原目录。')
                return {'manifest_hash':digest,'key':list(key)}
            temporary='.pending-'+uuid.uuid4().hex;os.mkdir(temporary,0o700,dir_fd=parent);stage_fd=self.directory(parent,temporary,False)
            for name,data in files.items():self.put_file(stage_fd,name,data)
            self.put_file(stage_fd,'manifest.json',raw);os.fsync(stage_fd);os.close(stage_fd);stage_fd=None
            os.rename(temporary,key[-1],src_dir_fd=parent,dst_dir_fd=parent);temporary=None;os.fsync(parent)
            return {'manifest_hash':checksum(raw),'key':list(key)}
        except (OSError,ValueError,KeyError,TypeError) as error:
            raise ArchiveFileError('归档未完成或内容冲突，请检查磁盘及权限后主动重试；旧归档未覆盖。') from error
        finally:
            if stage_fd is not None:os.close(stage_fd)
            if temporary is not None and parent is not None:
                # Only remove this invocation's known staging files, never recurse
                # into directories supplied by a manifest or an API caller.
                try:
                    fd=self.directory(parent,temporary,False)
                    try:
                        for name in [*files,'manifest.json']:
                            try:os.unlink(name,dir_fd=fd)
                            except FileNotFoundError:pass
                    finally:os.close(fd)
                    os.rmdir(temporary,dir_fd=parent)
                except OSError:pass
            if lock is not None:os.close(lock)
            if parent is not None:os.close(parent)

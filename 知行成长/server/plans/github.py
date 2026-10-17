"""GitHub content storage. No checkout, disk cache, tokens in URLs or force pushes."""
import base64
import os
import re
from collections import OrderedDict
from pathlib import PurePosixPath
from threading import RLock
from urllib.parse import quote

import httpx
from copilot.core import digest, fail


class GitHubContent:
    def __init__(self, repository, branch, token, transport=None):
        self.repository, self.branch, self.token = repository, branch, token
        self.transport = transport
        self.cache = OrderedDict()
        self.cache_lock = RLock()

    @classmethod
    def from_env(cls):
        return cls(os.getenv('GITHUB_CONTENT_REPO', ''), os.getenv('GITHUB_CONTENT_BRANCH', 'main'),
                   os.getenv('GITHUB_CONTENT_TOKEN', ''))

    def validate(self):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', self.repository) or not self.token:
            fail('github_config', '请配置内容仓库 GITHUB_CONTENT_REPO 和后端凭证 GITHUB_CONTENT_TOKEN。', 503)
        if not self.branch or self.branch.startswith('-') or any(x in self.branch for x in ('..', '?', '#', '\\', ' ')):
            fail('github_config', '内容仓库分支配置无效。', 503)

    def path(self, relative):
        if not isinstance(relative, str):fail('invalid', '课程路径必须是字符串。', 422)
        p = PurePosixPath(relative)
        if (not relative.startswith('学习计划/') or
                p.is_absolute() or '..' in p.parts or '\\' in relative or
                any(ord(c) < 32 for c in relative) or str(p) != relative or
                p.name == '学习记录.md'):
            fail('invalid', '路径不属于学习计划或含有无效片段。', 422)
        return quote(relative, safe='/')

    def request(self, method, endpoint, missing=False, empty=False, **kwargs):
        self.validate()
        try:
            with httpx.Client(timeout=httpx.Timeout(25, connect=10), follow_redirects=False,
                              transport=self.transport) as client:
                url = 'https://api.github.com/repos/'+self.repository+('/'+endpoint if endpoint else '')
                r = client.request(method, url,
                    headers={'Authorization': 'Bearer '+self.token, 'Accept': 'application/vnd.github+json',
                             'X-GitHub-Api-Version': '2026-03-10'}, **kwargs)
        except httpx.HTTPError:
            fail('github_unavailable', 'GitHub 连接中断，草稿和发布任务已保留；请稍后检查未完成保存。', 503)
        if r.status_code == 404 and missing: return None
        if r.status_code == 409 and empty: return None
        if r.status_code in (409, 422):
            fail('github_conflict', 'GitHub 分支已变化或拒绝提交；任务已保留，请检查分支权限后重试。', 409)
        if r.status_code in (401, 403, 404):
            fail('github_access', 'GitHub 暂不可访问，请检查内容仓库、分支、凭证权限或 API 限流。', 503)
        if not 200 <= r.status_code < 300:
            fail('github_unavailable', 'GitHub 暂时不可用；任务已保留，请稍后重试。', 503)
        try: return r.json()
        except ValueError: fail('github_invalid', 'GitHub 返回了无法识别的内容。', 502)

    def head(self):
        data = self.request('GET', 'git/ref/heads/'+quote(self.branch, safe='/'), missing=True, empty=True)
        if data: return data['object']['sha']
        # Distinguish a genuinely empty repository from a typo, inaccessible repo,
        # or missing branch in an existing repository. Reads never create commits.
        repo = self.request('GET', '')
        refs = self.request('GET', 'git/matching-refs/heads/', empty=True)
        if refs or repo.get('default_branch') != self.branch:
            fail('github_access', '目标分支不存在，请先在 GitHub 创建该分支。', 503)
        return None

    def bootstrap(self):
        if self.head(): return
        self.request('PUT', 'contents/README.md', json={
            'message': 'Initialize learning content repository', 'branch': self.branch,
            'content': base64.b64encode('# 学习内容\n\n由知行成长平台发布的学习规划、课程和参考资料。\n'.encode()).decode()})

    def entry(self, relative, ref):
        return self.request('GET', 'contents/'+self.path(relative), missing=True, params={'ref': ref})

    def exists(self, relative, ref):
        self.path(relative)
        if ref is None: return False
        return self.entry(relative, ref) is not None

    def read_text(self, relative, ref=None, missing=False):
        # Only immutable commit-addressed results are cached. Missing files are not cached.
        self.path(relative)
        ref = ref or self.head()
        if ref is None:
            if missing:return None
            fail('not_found', '内容仓库尚未发布课程。', 404)
        key = (ref, relative)
        with self.cache_lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
        data = self.entry(relative, ref)
        if data is None:
            if missing: return None
            fail('not_found', 'GitHub 中未找到该课程文件。', 404)
        if not isinstance(data, dict) or data.get('type') != 'file' or data.get('encoding') != 'base64':
            fail('github_invalid', '课程必须为不超过 1 MB 的普通 UTF-8 文件。', 422)
        try: text = base64.b64decode(data['content']).decode('utf-8')
        except (ValueError, UnicodeError): fail('github_invalid', '课程文件编码无效。', 422)
        with self.cache_lock:
            self.cache[key] = text
            while len(self.cache) > 128: self.cache.popitem(last=False)
        return text

    def prepare(self, head, files, operation):
        commit = self.request('GET', 'git/commits/'+head)
        entries = [{'path': path, 'mode': '100644', 'type': 'blob', 'content': value}
                   for path, value in files.items()]
        for path in files: self.path(path)
        tree = self.request('POST', 'git/trees', json={'base_tree': commit['tree']['sha'], 'tree': entries})
        return self.request('POST', 'git/commits', json={
            'message': 'Publish learning content\n\nPublication: '+digest(operation),
            'tree': tree['sha'], 'parents': [head]})['sha']

    def advance(self, sha):
        self.request('PATCH', 'git/refs/heads/'+quote(self.branch, safe='/'), json={'sha': sha, 'force': False})

    def contains(self, sha, head):
        if sha == head: return True
        result = self.request('GET', 'compare/'+sha+'...'+head)
        return result['status'] in ('ahead', 'identical')

    def url(self, relative, ref):
        return 'https://github.com/'+self.repository+'/blob/'+quote(ref, safe='')+'/'+self.path(relative)

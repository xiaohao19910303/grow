"""Disposable PostgreSQL records and an HTTP-level GitHub content repository."""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from cloud_content import ModuleContent
from copilot.cloud_store import CloudStore
from legacy_schema import migrate
from legacy_files import preview, apply
from plans.github import GitHubContent
from plans.github_store import GitHubPlans
from reading.cloud_store import CloudReadingStore
from test_github_plans import Repository
from test_legacy_cloud_schema import PostgreSQLFixture


class CloudFixture(PostgreSQLFixture):
    def setUp(self):
        super().setUp()
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.runtime=self.root/'runtime'
        self.repo=Repository();transport=httpx.MockTransport(self.repo)
        self.content=GitHubContent('owner/courses','main','TEST_ONLY_TOKEN',transport=transport)
        self.module_content=ModuleContent('owner/courses','main','TEST_ONLY_TOKEN',transport=transport)
        async def article_text(url):return 'Synthetic public article. Evidence and boundaries. '*20
        for mock in (patch.dict('os.environ',{'PLAN_CONTENT_BACKEND':'github','CLOUD_DEPLOY':'0'}),
                     patch('plans.github.GitHubContent.from_env',return_value=self.content),
                     patch('reading.service.fetch_article_content',side_effect=article_text),
                     patch('cloud_content.configured_content',return_value=self.module_content)):
            mock.start();self.addCleanup(mock.stop)
        migrate()
        self.s=self.new_plans();self.s.initialize()

    def new_plans(self):return GitHubPlans(self.root,self.runtime,self.content)
    def new_course(self):return CloudStore(self.root,self.runtime,self.module_content)
    def new_reading(self):return CloudReadingStore(self.root,self.runtime,self.module_content)

    def seed_courses(self):
        from copilot.core import MODULE
        shutil.copytree(Path(__file__).parent/'fixtures/renzhi',self.root/MODULE)
        course=self.new_course();course.initialize()
        report=preview(course.documents,self.root);apply(course.documents,self.root,report['token'])
        return course

    def public(self,path):return self.content.read_text(path,self.repo.head)
    def external(self,path,text):
        sha=self.repo.sha();files=dict(self.repo.commits[self.repo.head]['files'])
        if text is None:files.pop(path,None)
        else:files[path]=text
        self.repo.commits[sha]={'files':files,'parents':[self.repo.head]};self.repo.head=sha
        return sha


class AsyncCloudFixture(CloudFixture,unittest.IsolatedAsyncioTestCase):
    pass

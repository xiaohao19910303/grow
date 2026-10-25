"""Progress publishing must retain trusted tenant and repository selection."""
from contextlib import contextmanager
from unittest.mock import patch
import action_plans as actions
from action_source_worker import sweep
from cloud_fixtures import CloudFixture
from tenancy import current_user
from mobile_progress import source_url


class MobileProgressTests(CloudFixture):
    def test_worker_retains_server_owned_custom_github_context(self):
        with actions.connection():pass
        with self.s.conn() as c:
            c.execute('CREATE TABLE auth_users (id TEXT,schema_name TEXT,is_owner INTEGER,github_config TEXT)')
            c.execute('INSERT INTO auth_users VALUES (?,?,?,?)',('worker-owner',self.schema,1,'{"mode":"custom"}'))
        store=self.s
        class Accounts:
            @contextmanager
            def conn(self):
                with store.conn() as c:yield c
        seen=[]
        with patch('mobile_progress.sync',lambda s:seen.append(dict(current_user.get()))):sweep(Accounts(),store)
        self.assertEqual(len(seen),1);self.assertEqual(seen[0]['github_config'],'{"mode":"custom"}')
        self.assertEqual(seen[0]['schema_name'],self.schema)

    def test_mobile_url_configuration_never_accepts_credentials_or_arbitrary_http(self):
        for value in ('https://user:password@example.org/','https://example.org/?token=private','http://example.org/','https://example.org/#private'):
            with patch.dict('os.environ',{'GROW_PUBLIC_URL':value}):self.assertIsNone(source_url())
        with patch.dict('os.environ',{'GROW_PUBLIC_URL':'https://grow.example/'}):self.assertEqual(source_url(),'https://grow.example/')

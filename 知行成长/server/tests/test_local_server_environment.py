"""Local restarts load storage configuration without importing deployment secrets."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from run_local import load_environment


class LocalServerEnvironmentTests(unittest.TestCase):
    def test_storage_configuration_precedence_and_deployment_password_is_not_loaded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            server = root / 'platform/server'
            server.mkdir(parents=True)
            (root / '.env.local').write_text('DATABASE_URL=shared\nGITHUB_CONTENT_TOKEN=test-token\nAPP_PASSWORD=obsolete-password\nRENDER_API_KEY=unrelated\nQWEN_API_KEY=old-ai\n')
            (server / '.env').write_text('DATABASE_URL=server\nPLAN_CONTENT_BACKEND=github\nGITHUB_CONTENT_REPO=owner/courses\n')
            with patch.dict(os.environ, {'GITHUB_CONTENT_TOKEN': 'explicit-token'}, clear=True):
                load_environment(server)
                self.assertEqual(os.environ['DATABASE_URL'], 'server')
                self.assertEqual(os.environ['GITHUB_CONTENT_TOKEN'], 'explicit-token')
                self.assertEqual(os.environ['PLAN_CONTENT_BACKEND'], 'github')
                for key in ('APP_PASSWORD', 'RENDER_API_KEY', 'QWEN_API_KEY'):
                    self.assertNotIn(key, os.environ)

    def test_env_text_is_not_executed_and_parse_errors_do_not_disclose_values(self):
        from run_local import read_env
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / '.env'
            path.write_text("export GITHUB_CONTENT_TOKEN='$(do-not-run)' # comment\n")
            self.assertEqual(read_env(path)['GITHUB_CONTENT_TOKEN'], '$(do-not-run)')
            path.write_text("GITHUB_CONTENT_TOKEN='private-invalid-value\n")
            with self.assertRaises(ValueError) as error:
                read_env(path)
            self.assertNotIn('private-invalid-value', str(error.exception))

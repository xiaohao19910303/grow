"""Cloud authentication guards the same browser routes used by the plan pilot."""
import os
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from copilot.api import register


class CloudAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'CLOUD_DEPLOY':'1', 'PLAN_CONTENT_BACKEND':'github',
            'APP_USERNAME':'owner', 'APP_PASSWORD':'test-password-with-at-least-24-characters'})
        self.env.start(); self.addCleanup(self.env.stop)
        app = FastAPI(); register(app, '/nonexistent-root', '/nonexistent-runtime')
        @app.get('/')
        def root():return {'ok':True}
        @app.get('/api/health')
        def health():return {'ok':True}
        @app.get('/api/plans')
        def plans():return {'plans':[]}
        self.client = TestClient(app, base_url='https://cloud.example', client=('198.51.100.1',1234))

    def test_cloud_routes_require_login_and_health_is_public(self):
        self.assertEqual(self.client.get('/').status_code, 401)
        self.assertEqual(self.client.get('/api/plans').status_code, 401)
        self.assertEqual(self.client.get('/api/health').status_code, 200)
        self.assertIn('Basic', self.client.get('/').headers['WWW-Authenticate'])

    def test_authenticated_remote_browser_can_read_and_cross_origin_is_rejected(self):
        auth = ('owner', os.environ['APP_PASSWORD'])
        self.assertEqual(self.client.get('/api/plans', auth=auth).status_code, 200)
        self.assertEqual(self.client.get('/api/plans', auth=auth, headers={'Origin':'https://evil.example'}).status_code, 403)
        self.assertEqual(self.client.get('/api/plans', auth=('owner','wrong')).status_code, 401)

    def test_missing_or_malformed_credentials_fail_closed(self):
        self.assertEqual(self.client.get('/', headers={'Authorization':'Basic !!!'}).status_code, 401)
        with patch.dict(os.environ, {'APP_PASSWORD':''}):
            self.assertEqual(self.client.get('/').status_code, 503)


if __name__ == '__main__':unittest.main()

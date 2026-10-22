"""Standalone entrypoint rejects unsafe/incomplete configuration without leaking it."""
import os
import unittest
from cryptography.fernet import Fernet
from deployment import validate_config, ConfigurationError

class DeploymentConfigurationTests(unittest.TestCase):
    def config(self):
        return dict(DATABASE_URL='postgresql://test:PRIVATE_DB_PASSWORD@127.0.0.1/grow_test',
                    APP_USERNAME='owner',APP_PASSWORD='TEST_ONLY_ADMIN_PASSWORD_123456',
                    ACCOUNT_ENCRYPTION_KEY=Fernet.generate_key().decode(),PLAN_CONTENT_BACKEND='github')

    def test_core_web_works_without_ai_github_or_bridge_credentials(self):
        report=validate_config(self.config())
        self.assertTrue(report['ok']);self.assertIn('github_content_unconfigured',report['warnings'])
        self.assertNotIn('PRIVATE',str(report))

    def test_invalid_values_are_rejected_with_names_but_no_secrets(self):
        for key,value in [('DATABASE_URL',''),('DATABASE_URL','sqlite:///tmp/private'),('APP_PASSWORD','short'),
                          ('ACCOUNT_ENCRYPTION_KEY','PRIVATE_INVALID_KEY'),('WEB_CONCURRENCY','2'),
                          ('PLAN_CONTENT_BACKEND','local')]:
            with self.subTest(key=key):
                data=self.config();data[key]=value
                with self.assertRaises(ConfigurationError) as error:validate_config(data)
                self.assertIn(key,str(error.exception));self.assertNotIn('PRIVATE',str(error.exception))

    def test_example_placeholders_are_never_accepted_as_real_credentials(self):
        for key,value in [('DATABASE_URL','postgresql://grow_user:CHANGE_ME@127.0.0.1:5432/grow'),
                          ('APP_PASSWORD','REPLACE_WITH_AT_LEAST_24_RANDOM_CHARACTERS'),
                          ('ACCOUNT_ENCRYPTION_KEY','REPLACE_WITH_FERNET_KEY')]:
            with self.subTest(key=key):
                data=self.config();data[key]=value
                with self.assertRaises(ConfigurationError):validate_config(data)

    def test_configuration_does_not_mutate_environment(self):
        data=self.config();copy=dict(data);validate_config(data);self.assertEqual(data,copy)

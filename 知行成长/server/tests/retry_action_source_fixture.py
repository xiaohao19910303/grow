"""Fresh Grow process runs the actual worker sweep against an owned test schema."""
from datetime import datetime
import os
import re
from unittest.mock import patch
import db
from action_source_worker import sweep

schema=os.environ['TEST_GROW_SOURCE_SCHEMA'];dsn=os.environ['TEST_LEGACY_PG_DSN']
if not re.fullmatch(r'legacy_cloud_[a-f0-9]{32}',schema) or 'host=127.0.0.1' not in dsn:raise RuntimeError('Owned localhost schema required')
original=db.connect
class Accounts:
    def conn(self):return original(dsn+' options=-csearch_path='+schema,tenant=False)
with patch('db.connect',lambda *a,**kw:original(dsn+' options=-csearch_path='+schema)),patch('action_plans.clock',return_value=datetime.fromisoformat(os.environ['TEST_SOURCE_NOW'])):
    sweep(Accounts())

"""Fresh Grow retry, restricted to a disposable local schema and server."""
import os
import re
from unittest.mock import patch
from urllib.parse import urlsplit
import db
from tenancy import current_user
from test_action_handoff_cutover import signed_send
from action_handoff_coordinator import finish_v2
schema=os.environ['TEST_GROW_SOURCE_SCHEMA'];url=os.environ['TEST_HANDOFF_URL'];dsn=os.environ['TEST_LEGACY_PG_DSN']
if not re.fullmatch(r'legacy_cloud_[a-f0-9]{32}',schema) or urlsplit(url).hostname!='127.0.0.1' or 'host=127.0.0.1' not in dsn:raise RuntimeError('Disposable localhost fixtures required')
original=db.connect
current_user.set({'id':'grow-fixture','schema_name':schema,'is_owner':1})
with patch('db.connect',lambda *a,**kw:original(dsn+' options=-csearch_path='+schema,tenant=False)):
    print(finish_v2('grow-fixture',lambda source,body:signed_send(url,os.environ['TEST_HANDOFF_TOKEN'],source,body)))

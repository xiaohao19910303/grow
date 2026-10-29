"""Pinned connections cannot re-resolve an approved hostname into a private address."""
from unittest import IsolatedAsyncioTestCase,TestCase
from unittest.mock import patch
import httpcore
from copilot.core import Problem
from investments.bounded_http import PinnedBackend,public_addresses


class PublicDestinationTests(TestCase):
    def test_private_mixed_and_unapproved_destinations_are_rejected(self):
        for address in ('127.0.0.1','10.0.0.1','169.254.169.254','::1','::ffff:127.0.0.1'):
            with patch('socket.getaddrinfo',return_value=[(2,1,6,'',(address,443))]),self.assertRaises(Problem):
                public_addresses('https://model.example/v1',{'model.example'})
        with self.assertRaises(Problem):public_addresses('https://other.example/v1',{'model.example'})


class PinnedConnectionTests(IsolatedAsyncioTestCase):
    async def test_tcp_uses_checked_ip_and_preserves_hostname_constraint(self):
        connected=[]
        class Backend:
            async def connect_tcp(self,host,port,**kwargs):connected.append((host,port));return 'stream'
        backend=PinnedBackend('model.example',['93.184.216.34'],Backend())
        with patch('socket.getaddrinfo',side_effect=AssertionError('must not re-resolve')):
            self.assertEqual(await backend.connect_tcp('model.example',443),'stream')
        self.assertEqual(connected,[('93.184.216.34',443)])
        with self.assertRaises(httpcore.ConnectError):await backend.connect_tcp('127.0.0.1',443)

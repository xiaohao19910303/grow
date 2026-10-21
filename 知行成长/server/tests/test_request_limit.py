"""Request bursts queue before database/auth work; health checks stay responsive."""
import asyncio
import unittest
import httpx
from fastapi import FastAPI
from request_limit import RequestConcurrencyLimit


class RequestLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_burst_including_auth_work_queues_without_dropping_requests(self):
        app = FastAPI()
        active, peak = 0, 0

        @app.middleware('http')
        async def authentication(request, call_next):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(.005)
                return await call_next(request)
            finally:
                active -= 1

        @app.get('/api/data')
        async def data():
            await asyncio.sleep(.005)
            return {'preserved': True}

        app.add_middleware(RequestConcurrencyLimit, limit=4)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            responses = await asyncio.gather(*(client.get('/api/data') for _ in range(30)))
        self.assertEqual(peak, 4)
        self.assertEqual(active, 0)
        self.assertTrue(all(r.status_code == 200 and r.json() == {'preserved': True} for r in responses))

    async def test_health_bypasses_queue_and_cancellation_releases_slot(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def inner(scope, receive, send):
            if scope['path'] == '/api/slow':
                entered.set()
                await release.wait()
            if scope['path'] == '/api/error':
                raise RuntimeError('synthetic failure')
            await send({'type': 'http.response.start', 'status': 200, 'headers': []})
            await send({'type': 'http.response.body', 'body': b'ok'})

        app = RequestConcurrencyLimit(inner, limit=1)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            slow = asyncio.create_task(client.get('/api/slow'))
            await entered.wait()
            response = await asyncio.wait_for(client.get('/api/health'), timeout=1)
            self.assertEqual(response.status_code, 200)
            slow.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await slow
            with self.assertRaises(RuntimeError):
                await client.get('/api/error')
            response = await asyncio.wait_for(client.get('/api/data'), timeout=1)
            self.assertEqual(response.status_code, 200)

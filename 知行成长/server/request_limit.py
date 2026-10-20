"""Queue database-backed requests before authentication opens a connection."""
import asyncio


class RequestConcurrencyLimit:
    def __init__(self, app, limit=4):
        self.app = app
        # One request can hold an advisory-lock connection and a working connection.
        # Leave headroom in the shared 15-session database pool for background work.
        self.slots = asyncio.Semaphore(limit)

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        if scope['type'] != 'http' or path in ('/api/health', '/login') or path.startswith('/static/'):
            await self.app(scope, receive, send)
            return
        async with self.slots:
            await self.app(scope, receive, send)

"""Compress large retained market responses without caching or changing their data."""
from starlette.middleware.gzip import GZipMiddleware


class MarketCompression:
    def __init__(self, app):
        self.app = app
        self.compressed = GZipMiddleware(app, minimum_size=2048, compresslevel=3)

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        market = (path in {'/api/v1/quotes', '/api/v1/games', '/api/v1/live-stoppages',
                           '/api/refresh/v1/props', '/api/refresh/v1/props/trends',
                           '/api/refresh/v1/props/trends/options', '/api/refresh/v1/props/trends/board'}
                  or path.startswith('/api/v1/tools/')
                  or (path.startswith('/api/v1/games/') and path.endswith('/odds')))
        app = self.compressed if scope['type'] == 'http' and scope.get('method') == 'GET' and market else self.app
        await app(scope, receive, send)

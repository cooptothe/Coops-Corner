"""Local fixture-only product API. No DB config, secrets, jobs or external IO."""
import asyncio
from decimal import Decimal
from fractions import Fraction
import json
from typing import Annotated
from urllib.parse import urlsplit
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.staticfiles import StaticFiles

from api.catalog import FixtureCatalog, APIProblem, paginate
from api.models import (Envelope, Page, Game, Quote, ToolRow, ToolKind, GameQuery, QuoteQuery, BulkQuoteQuery, ToolQuery,
                        PromoRequest, PromoResponse, ErrorEnvelope, ErrorDetail, Capabilities, Health)
from corner.featured_markets import SUPPORTED_MARKETS
from corner.featured_tools import ToolInputError

LOCAL_HOSTS = {'localhost', '127.0.0.1', '::1'}
DEFAULT_ORIGINS = ('http://localhost:5173', 'http://127.0.0.1:5173', 'http://localhost:3000', 'http://127.0.0.1:3000')


def error_response(catalog, status, code, message, fields=()):
    result = ErrorEnvelope(meta=catalog.meta(), error=ErrorDetail(code=code, message=message, fields=list(fields)))
    return JSONResponse(result.model_dump(mode='json'), status_code=status, headers={'Cache-Control': 'no-store'})


def _unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON field')
        result[key] = value
    return result


class RequestBoundary:
    """Bounded bodies/queries, local Host protection, deterministic JSON parsing."""
    def __init__(self, app, catalog):
        self.app, self.catalog = app, catalog

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)

        async def reject(status, code, message):
            await error_response(self.catalog, status, code, message)(scope, receive, send)

        headers = {key.lower(): value for key, value in scope['headers']}
        try:
            host = urlsplit('http://' + headers.get(b'host', b'').decode('ascii'))
            if host.hostname not in LOCAL_HOSTS or host.username is not None or host.path:
                return await reject(400, 'invalid_host', 'Only a local host is supported.')
        except (ValueError, UnicodeError):
            return await reject(400, 'invalid_host', 'Only a local host is supported.')
        if len(scope.get('query_string', b'')) > 2048:
            return await reject(414, 'query_too_large', 'Query exceeds 2048 bytes.')
        if scope['path'].startswith('/api/v1'):
            query = Request(scope).query_params
            if len(query.multi_items()) != len(query):
                return await reject(422, 'duplicate_query_parameter', 'Each query parameter may be supplied once.')
        if headers.get(b'content-encoding', b'identity').lower() != b'identity':
            return await reject(415, 'unsupported_encoding', 'Compressed request bodies are not supported.')
        try:
            length = int(headers.get(b'content-length', b'0'))
            if length < 0:
                raise ValueError()
        except ValueError:
            return await reject(400, 'invalid_content_length', 'Invalid Content-Length.')
        if length > 16384:
            return await reject(413, 'body_too_large', 'Request exceeds 16384 bytes.')
        chunks, size = [], 0
        body_deadline = asyncio.get_running_loop().time() + 10
        while True:
            try:
                remaining = body_deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TimeoutError()
                message = await asyncio.wait_for(receive(), timeout=remaining)
            except TimeoutError:
                return await reject(408, 'body_timeout', 'Request body did not arrive in time.')
            if message['type'] == 'http.disconnect':
                return
            chunk = message.get('body', b'')
            size += len(chunk)
            if size > 16384:
                return await reject(413, 'body_too_large', 'Request exceeds 16384 bytes.')
            chunks.append(chunk)
            if not message.get('more_body', False):
                break
        body = b''.join(chunks)
        if scope['method'] == 'POST':
            content_type = headers.get(b'content-type', b'').split(b';', 1)[0].strip().lower()
            if content_type != b'application/json':
                return await reject(415, 'json_required', 'Use Content-Type: application/json.')
            try:
                json.loads(body, object_pairs_hook=_unique_json,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
            except (ValueError, UnicodeError, RecursionError):
                return await reject(400, 'invalid_json', 'Body must be valid JSON without duplicate fields or nonfinite values.')
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            return await receive()

        async def safe_headers(message):
            if message['type'] == 'http.response.start':
                message['headers'] = list(message.get('headers', [])) + [
                    (b'cache-control', b'no-store'), (b'x-content-type-options', b'nosniff'),
                    (b'x-corner-data-mode', self.catalog.data_mode.encode())]
            await send(message)

        await self.app(scope, replay, safe_headers)


class SessionGate:
    """Requires a valid session cookie for every /api/v1 call. `check(token)` says whether a token is good."""
    def __init__(self, app, check, catalog, cookie='corner_session'):
        self.app, self.check, self.catalog, self.cookie = app, check, catalog, cookie.encode()

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not scope['path'].startswith('/api/v1'):
            return await self.app(scope, receive, send)
        token = None
        for key, value in scope['headers']:
            if key == b'cookie':
                for part in value.split(b';'):
                    name, _, raw = part.strip().partition(b'=')
                    if name == self.cookie:
                        token = raw.decode('ascii', 'ignore')
        if not token or not self.check(token):
            return await error_response(self.catalog, 401, 'auth_required', 'Sign in to continue.')(scope, receive, send)
        await self.app(scope, receive, send)


def create_app(*, data_mode='fixture', catalog=None, cors_origins=DEFAULT_ORIGINS, session_check=None):
    if data_mode not in {'fixture', 'database'} or (data_mode == 'database' and catalog is None):
        raise ValueError('Use fixture mode, or database mode with an explicit read-only catalog; there is no live fallback.')
    for origin in cors_origins:
        url = urlsplit(origin)
        if (url.scheme not in {'http', 'https'} or url.hostname not in LOCAL_HOSTS
                or url.username is not None or url.password is not None or url.path or url.query or url.fragment):
            raise ValueError('CORS origins must be explicit loopback origins.')
        _ = url.port  # validate the port, too
    catalog = catalog if catalog is not None else FixtureCatalog()
    if catalog.data_mode != data_mode:
        raise ValueError('catalog data mode does not match the requested mode')
    api = FastAPI(title='The Corner â€” Fixture Product API', version='1.0.0', redirect_slashes=False,
                  description='Synthetic local development API. No live odds, DB access, production authorization or bet execution.',
                  responses={code: {'model': ErrorEnvelope} for code in (400, 404, 409, 413, 415, 422, 500)})
    api.state.catalog = catalog
    api.add_middleware(RequestBoundary, catalog=catalog)
    if session_check is not None:
        api.add_middleware(SessionGate, check=session_check, catalog=catalog)
    api.add_middleware(CORSMiddleware, allow_origins=list(cors_origins), allow_credentials=False,
                       allow_methods=['GET', 'POST'], allow_headers=['Content-Type'], expose_headers=['X-Corner-Data-Mode'])

    @api.exception_handler(APIProblem)
    async def domain_problem(request, exc):
        return error_response(catalog, exc.status, exc.code, exc.message)

    @api.exception_handler(ToolInputError)
    async def invalid_calculation(request, exc):
        return error_response(catalog, 422, 'invalid_calculation', str(exc))

    @api.exception_handler(RequestValidationError)
    async def validation(request, exc):
        fields = ['.'.join(map(str, item['loc'])) for item in exc.errors()]
        return error_response(catalog, 422, 'invalid_request', 'Request does not match the API contract.', fields)

    @api.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error_response(catalog, exc.status_code, 'http_error', 'Route or method is not supported.')

    @api.exception_handler(Exception)
    async def unexpected(request, exc):
        # Do not return exception text, request bodies or misleading empty data.
        return error_response(catalog, 500, 'internal_error', 'The request could not be completed.')

    def result(data):
        return {'meta': catalog.meta(), 'data': data}

    @api.get('/api/v1/health', response_model=Envelope[Health], tags=['system'])
    def health():
        return result(Health())

    @api.post('/api/v1/catalog/reload', tags=['system'])
    def reload_catalog():
        # Re-reads the database only; the Odds API is never called from this process.
        if hasattr(catalog, 'reload'):
            catalog.reload()
        return result({'games': len(catalog.games), 'rows': len(catalog.rows)})

    @api.get('/api/v1/capabilities', response_model=Envelope[Capabilities], tags=['system'])
    def capabilities():
        return result(Capabilities(market_keys=list(SUPPORTED_MARKETS), tools=['positive_ev', 'arbitrage', 'low_hold', 'middle'],
                      books=list(catalog.books), sports=sorted({g.sport_key for g in catalog.games}),
                      calculator_defaults={'ev_stake': '100', 'back_cover_total_stake': '200', 'back_lay_back_stake': '100',
                                           'middle_leg_stake': '100', 'stake_increment': '0.01'},
                      unsupported=['live_mode', 'bet_placement', 'tracker', 'bankroll', 'clv', 'sharp_money', 'insiders']))

    @api.get('/api/v1/games', response_model=Envelope[Page[Game]], tags=['games'])
    def games(query: Annotated[GameQuery, Query()]):
        catalog.verify_snapshot(query.snapshot_id)
        games = [g for g in catalog.games if (query.sport_key is None or query.sport_key == g.sport_key)
                 and (query.market_key is None or query.market_key in g.market_keys)
                 and (query.search is None or query.search.casefold() in (g.name + ' ' + g.competition).casefold())]
        return result(paginate(games, query))

    @api.get('/api/v1/games/{game_id}', response_model=Envelope[Game], tags=['games'])
    def game(game_id: str):
        return result(catalog.game(game_id))

    @api.get('/api/v1/games/{game_id}/odds', response_model=Envelope[Page[Quote]], tags=['games'])
    def odds(game_id: str, query: Annotated[QuoteQuery, Query()]):
        catalog.verify_snapshot(query.snapshot_id)
        catalog.game(game_id)
        quotes = [q for q in catalog.quotes_by_game.get(game_id, ())
                  if (query.market_key is None or query.market_key == q.market_key)
                  and (query.sportsbook_id is None or query.sportsbook_id == q.sportsbook_id)
                  and (query.contract_id is None or query.contract_id == q.contract_id)]
        return result(paginate(quotes, query, ('decimal_odds',)))

    @api.get('/api/v1/quotes', response_model=Envelope[Page[Quote]], tags=['games'])
    def all_quotes(query: Annotated[BulkQuoteQuery, Query()]):
        catalog.verify_snapshot(query.snapshot_id)

        def matching():
            return [q for q in catalog.quotes
                    if (query.market_key is None or query.market_key == q.market_key)
                    and (query.sportsbook_id is None or query.sportsbook_id == q.sportsbook_id)
                    and (query.contract_id is None or query.contract_id == q.contract_id)]

        which = ('quotes', query.market_key, query.sportsbook_id, query.contract_id)
        return result(paginate(matching, query, ('decimal_odds',), memo=catalog.memo, memo_key=which))

    @api.get('/api/v1/tools/{kind}', response_model=Envelope[Page[ToolRow]], tags=['tools'])
    def tools(kind: ToolKind, query: Annotated[ToolQuery, Query()]):
        catalog.verify_snapshot(query.snapshot_id)
        if query.game_id is not None:
            catalog.game(query.game_id)
        if kind != 'positive_ev' and query.devig_method != 'current':
            raise APIProblem(422, 'inapplicable_filter', 'devig_method applies only to positive_ev.')
        if kind != 'positive_ev' and query.minimum_ev_ratio != '0':
            raise APIProblem(422, 'inapplicable_filter', 'minimum_ev_ratio applies only to positive_ev.')
        if kind != 'low_hold' and query.maximum_loss_ratio != '0.01':
            raise APIProblem(422, 'inapplicable_filter', 'maximum_loss_ratio applies only to low_hold.')
        loss_limit, minimum_ev = Decimal(query.maximum_loss_ratio), Decimal(query.minimum_ev_ratio)
        if loss_limit > 1:
            raise APIProblem(422, 'invalid_filter', 'maximum_loss_ratio must be between zero and one.')
        if query.sort == 'conditional_ev_ratio' and kind != 'positive_ev':
            raise APIProblem(422, 'inapplicable_sort', 'conditional_ev_ratio applies only to positive_ev.')
        if query.sort == 'minimum_profit' and kind == 'positive_ev':
            raise APIProblem(422, 'inapplicable_sort', 'positive_ev has no minimum_profit projection.')
        def matching():
            source = catalog.ev_rows(query.devig_method) if kind == 'positive_ev' else catalog.rows
            rows = [row for row in source if row.kind == kind
                    and (query.game_id is None or query.game_id == row.game_id)
                    and (query.sport_key is None or query.sport_key == catalog.game_map[row.game_id].sport_key)
                    and (query.market_key is None or query.market_key == row.market_key)
                    and (query.sportsbook_id is None or query.sportsbook_id in row.sportsbook_ids)]
            if kind == 'positive_ev':
                rows = [r for r in rows if Decimal(r.conditional_ev_ratio) >= minimum_ev]
            if kind == 'low_hold':
                rows = [r for r in rows if -Fraction(Decimal(r.minimum_profit)) <= Fraction(loss_limit) * Fraction(Decimal(r.capital_required))]
            return rows

        # The filter, its ordering and the page are separate steps: paging through one feed sorts it once.
        which = (kind, query.game_id, query.sport_key, query.market_key, query.sportsbook_id, query.minimum_ev_ratio, query.maximum_loss_ratio, query.devig_method)
        return result(paginate(matching, query, ('conditional_ev_ratio', 'minimum_profit', 'capital_required'),
                               memo=catalog.memo, memo_key=which))

    @api.post('/api/v1/calculators/promo', response_model=Envelope[PromoResponse], tags=['calculators'])
    def promo(command: PromoRequest):
        return result(catalog.promo(command))

    # Static UI is last: API/docs keep their routes. Only this asset directory is
    # exposed, never the repo root, .env, fixtures, reports or credentials.
    api.mount('/', StaticFiles(directory=Path(__file__).resolve().parents[1] / 'frontend', html=True), name='frontend')
    return api


app = create_app()

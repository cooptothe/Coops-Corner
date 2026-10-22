"""Premium live API: wonya reads cached data; loopback cron queues worker work."""
from __future__ import annotations
from datetime import datetime, timezone
import hmac
from pathlib import Path
from typing import Any, Literal
from pydantic import BaseModel, Field
from fastapi import APIRouter, BackgroundTasks, Request
from starlette.concurrency import run_in_threadpool
from pipelines.accounts import AuthContext, reply, host_ok
from corner import live_odds

class BookAvailability(BaseModel):
    book: str
    active_market_count: int = Field(ge=0)
    active_markets: list[Literal['h2h','spreads','totals']]
    markets: list[dict[str, Any]]
    capture_fresh: bool
    status: Literal['active','no_active_lines','unknown']

class LiveGame(BaseModel):
    id: str
    sport_key: str
    home_team: str
    away_team: str
    commence_time: str
    is_live_inferred: bool
    game_stoppage_confirmed: bool
    is_suspended: bool | None
    status: Literal['active','no_active_lines','unknown']
    reason: str
    active_market_count: int = Field(ge=0)
    books: list[BookAvailability]
    opportunities: list[dict[str, Any]]

class LiveStatusFeed(BaseModel):
    format: Literal['corner.live_odds/1']
    as_of: str
    premium: bool
    enabled: bool
    state: str
    events: list[LiveGame]
    source: Literal['the-odds-api']
    refresh_seconds: Literal[60]
    freshness_seconds: Literal[90]
    monthly_subcap: int
    daily_subcap: int
    budget_basis: Literal['within_existing_main_pool']
    game_stoppage_confirmed: bool
    live_credits_accounted: int = 0
    live_daily_credits_accounted: int = 0

def create_router(ctx: AuthContext, *, path: Path | None = None) -> APIRouter:
    router = APIRouter()
    if path is None:
        from corner.collection_activation import STATE
        path = STATE

    @router.get('/api/v1/live-stoppages',response_model=LiveStatusFeed)
    async def stoppages(request: Request) -> Any:
        user, denied = ctx.require(request,write=False)
        if denied: return denied
        if not live_odds.premium(user):
            return reply(403,{'error':'Live tools are a Premium feature.','code':'premium_required'})
        try:
            data = await run_in_threadpool(live_odds.cached_feed,path)
            return reply(200,LiveStatusFeed.model_validate(data).model_dump(mode='json'))
        except Exception:
            return reply(503,{'error':'Live status is temporarily unavailable.','code':'live_unavailable'})

    @router.post('/api/v1/cron/refresh-live-odds',status_code=202)
    async def refresh(request: Request, background_tasks: BackgroundTasks) -> Any:
        # Caddy forwards public requests with X-Forwarded-*; this is internal only.
        if (not host_ok(request) or not request.client or request.client.host not in ('127.0.0.1','::1')
            or request.headers.get('origin')
            or any(h in request.headers for h in ('x-forwarded-for','forwarded','x-forwarded-host','x-forwarded-proto'))):
            return reply(403,{'error':'Internal scheduler only.'})
        cfg = live_odds.config()
        supplied = request.headers.get('authorization','')
        expected = 'Bearer '+str(cfg.get('cron_token',''))
        if not cfg or not hmac.compare_digest(supplied.encode(),expected.encode()):
            return reply(403,{'error':'Scheduler authentication required.'})
        background_tasks.add_task(live_odds.request_refresh,datetime.now(timezone.utc))
        return reply(202,{'state':'queued','interval_seconds':60,'provider_calls':0})
    return router

"""Authenticated beta offer preview. Payment initiation is deliberately not wired."""
from fastapi import APIRouter, Request
from starlette.responses import JSONResponse
from corner import beta_access, beta_terms

SUPPORT_EMAIL = 'admin@coopscorner.tech'


def create_router(ctx):
    router = APIRouter(prefix='/api/refresh/v1/billing')

    @router.get('/status')
    async def status(request: Request):
        _, denied = ctx.require(request, write=False)
        if denied:
            return denied
        return JSONResponse({
            'private_beta': beta_access.enabled(),
            'stage': 'preparation',
            'payments_enabled': False,
            'terms_version': beta_terms.VERSION,
            'trial_days': beta_terms.TRIAL_SECONDS//86400,
            'price_usd_cents': beta_terms.PRICE_USD_CENTS,
            'access_end_label': 'November 20, 2026, at 11:59 p.m. Central',
            'assets': list(beta_terms.ASSETS),
            'support_email': SUPPORT_EMAIL,
        }, headers={'Cache-Control':'no-store'})

    return router

"""Authenticated beta offer preview. Payment initiation is deliberately not wired."""
from fastapi import APIRouter, Request
from starlette.responses import JSONResponse
from corner import beta_access, beta_terms

SUPPORT_EMAIL = 'admin@coopscorner.tech'


def create_router(ctx):
    router = APIRouter(prefix='/api/refresh/v1/billing')

    @router.get('/status')
    async def status(request: Request):
        user, denied = ctx.require(request, write=False)
        if denied:
            return denied
        return JSONResponse({
            'private_beta': beta_access.enabled(),
            'membership': user.get('membership'),
            'stage': 'preparation',
            'payments_enabled': False,
            'terms_version': beta_terms.VERSION,
            'trial_days': beta_terms.TRIAL_SECONDS//86400,
            'price_usd_cents': beta_terms.PRICE_USD_CENTS,
            'standard_monthly_usd_cents': beta_terms.STANDARD_MONTHLY_USD_CENTS,
            'founder_monthly_usd_cents': beta_terms.FOUNDER_MONTHLY_USD_CENTS,
            'package_label': beta_terms.PACKAGE_LABEL,
            'founder': bool(user.get('founder')),
            'launch_monthly_usd_cents': beta_terms.FOUNDER_MONTHLY_USD_CENTS if user.get('founder') else beta_terms.STANDARD_MONTHLY_USD_CENTS,
            'access_end_label': 'November 20, 2026, at 11:59 p.m. Central',
            'assets': list(beta_terms.ASSETS),
            'support_email': SUPPORT_EMAIL,
        }, headers={'Cache-Control':'no-store'})

    @router.post('/requests')
    @router.post('/requests/{request_id}/submit')
    @router.post('/requests/{request_id}/cancel')
    async def unavailable(request: Request):
        _, denied = ctx.require(request, write=True)
        if denied:
            return denied
        return JSONResponse({'error':'Payments are not open yet. No funds should be sent.',
                             'code':'payments_disabled'}, status_code=503,
                            headers={'Cache-Control':'no-store'})

    return router

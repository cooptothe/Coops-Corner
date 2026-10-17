"""Authenticated beta offer preview. Payment initiation is deliberately not wired."""
from starlette.concurrency import run_in_threadpool
from corner.billing_config import checkout_config
from corner.beta_invoices import BetaInvoices
from corner.tracker_store import TrackerError

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
        config = checkout_config()
        return JSONResponse({
            'private_beta': beta_access.enabled(),
            'membership': user.get('membership'),
            'stage': 'manual_review' if config else 'preparation',
            'payments_enabled': bool(config),
            'checkout_eligible': bool(config) and user.get('role') == 'member' and user.get('access_kind') == 'preview',
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

    async def serve(request, operation, *, write):
        user, denied = ctx.require(request, write=write)
        if denied:
            return denied
        config = checkout_config()
        if config is None:
            return JSONResponse({'error':'Payments are not open yet. No funds should be sent.',
                                 'code':'payments_disabled'}, status_code=503,
                                headers={'Cache-Control':'no-store'})
        try:
            body = await request.json() if write else None
            if write and not isinstance(body,dict):
                raise TrackerError('Use a JSON object.',400,'invalid_payment')
            def work():
                invoices=BetaInvoices(ctx.store)
                return operation(invoices,user,body)
            result=await run_in_threadpool(work)
            return JSONResponse(result,headers={'Cache-Control':'no-store'})
        except (TrackerError, ValueError) as error:
            return JSONResponse({'error':str(error) if isinstance(error,TrackerError) else 'Invalid payment request.',
                                 'code':getattr(error,'code','invalid_payment')},
                                status_code=getattr(error,'status',400),headers={'Cache-Control':'no-store'})

    @router.get('/requests/current')
    async def current(request: Request):
        def work(invoices,user,body):
            payment=invoices.current(user['id'])
            if payment:
                payment=invoices.status(user['id'],payment['id'],instructions=True)
            return {'payment':payment}
        return await serve(request,work,write=False)

    @router.post('/requests')
    async def create(request: Request):
        def work(invoices,user,body):
            if set(body)!= {'asset','terms_version'}:
                raise TrackerError('Accept the current terms and choose a coin.',400,'payment_terms')
            ident=invoices.request(user['id'],body['asset'],body['terms_version'])
            return {'payment':invoices.status(user['id'],ident,instructions=True)}
        return await serve(request,work,write=True)

    @router.post('/requests/{request_id}/submit')
    async def submit(request: Request,request_id: str):
        def work(invoices,user,body):
            if set(body)!= {'transaction_id'}:
                raise TrackerError('Enter only the transaction reference.',400,'payment_reference')
            invoices.submit(user['id'],request_id,body['transaction_id'])
            return {'payment':invoices.status(user['id'],request_id)}
        return await serve(request,work,write=True)

    @router.post('/requests/{request_id}/cancel')
    async def cancel(request: Request,request_id: str):
        def work(invoices,user,body):
            if body:
                raise TrackerError('No extra fields are accepted.',400,'invalid_payment')
            invoices.cancel(user['id'],request_id)
            return {'payment':invoices.status(user['id'],request_id)}
        return await serve(request,work,write=True)

    return router

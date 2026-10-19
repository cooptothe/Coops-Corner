"""Origin-checked, bounded private welcome endpoints."""
import json
from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from corner import auth, invitation_welcome as welcome
from corner.tracker_store import TrackerError

def create_router(ctx):
    router=APIRouter(prefix='/api/refresh/v1/invitations')
    throttle=auth.Throttle(limit=60,window=900,lockout=900)
    @router.post('/{operation}')
    async def invitation(request:Request,operation:str):
        denied=ctx.check(request,write=True)
        if denied:return denied
        headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Robots-Tag':'noindex, nofollow'}
        try:
            if operation not in ('preview','accept','feedback'):raise TrackerError('Not found.',404)
            key=request.client.host if request.client else 'unknown'
            if throttle.retry_after(key):raise TrackerError('Please wait before trying again.',429)
            throttle.fail(key)
            raw=bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw)>12000:raise TrackerError('Request too large.',413)
            body=json.loads(raw)
            if not isinstance(body,dict):raise ValueError()
            allowed={'token'}|({'version','terms_version','eligible','agree'} if operation=='accept' else {'category','title','message'} if operation=='feedback' else set())
            if set(body)!=allowed:raise ValueError()
            def work():
                user=ctx.user(request) if operation in ('feedback','preview') else None
                with ctx.store._lock:
                    db=ctx.store._db
                    db.execute('BEGIN IMMEDIATE')
                    try:
                        result=(welcome.offer(db,body['token'],user) if operation=='preview' else
                                welcome.accept(db,body['token'],body) if operation=='accept' else
                                welcome.feedback(db,body['token'],body,user))
                        db.execute('COMMIT');return result
                    except BaseException:
                        db.execute('ROLLBACK');raise
            return JSONResponse(await run_in_threadpool(work),headers=headers)
        except (ValueError,TrackerError) as error:
            return JSONResponse({'error':str(error) if isinstance(error,TrackerError) else 'Invalid invitation request.'},status_code=getattr(error,'status',400),headers=headers)
    return router

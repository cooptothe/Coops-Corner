"""Saved filter settings and presets for each tool, per account (so they follow you to any browser).

GET returns everything the account has saved in one small response. Writes need the local UI origin and a
session, like every other private route. The server keeps the values small and plain but never interprets
them; each page validates what it reads back.
"""
from fastapi import APIRouter, Request

from corner.tracker_store import TrackerError


def create_router(ctx):
    router = APIRouter(prefix='/api/refresh/v1/settings')

    def object_body(body):
        if not isinstance(body, dict):
            raise TrackerError('The request body must be an object')
        return body

    @router.get('')
    async def everything(request: Request):
        return await ctx.serve(request, False, lambda ledger: ledger.settings())

    @router.put('/{tool}')
    async def put(tool: str, request: Request):
        return await ctx.with_body(request, lambda ledger, body: {
            'settings': ledger.put_settings(tool, object_body(body).get('settings'))})

    @router.post('/{tool}/presets')
    async def save_preset(tool: str, request: Request):
        return await ctx.with_body(request, lambda ledger, body: {
            'preset': ledger.save_preset(tool, object_body(body).get('name'), object_body(body).get('settings'))})

    @router.delete('/presets/{preset_id}')
    async def delete_preset(preset_id: str, request: Request):
        return await ctx.serve(request, True, lambda ledger: (ledger.delete_preset(preset_id), {'ok': True})[1])

    return router

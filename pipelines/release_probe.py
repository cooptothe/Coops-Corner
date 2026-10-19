"""Bounded anonymous GET-only deployment checks. No login, refresh, payments or provider calls."""
import argparse
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPSHandler, HTTPRedirectHandler, Request

HOSTS={'coopscorner.tech','www.coopscorner.tech','localhost','127.0.0.1','::1'}
CHECKS=[('/invite',200),('/login',200),('/lab',200),('/tracker',200),('/account',200),
        ('/manifest.webmanifest',200),('/assets/corner-icon-192.png',200),('/assets/corner-icon-512.png',200),
        ('/api/refresh/v1/auth/me',401),('/api/refresh/v1/billing/status',401),
        ('/api/refresh/v1/tracker/state',401),('/api/refresh/v1/props',401),
        ('/api/refresh/v1/props/trends/options',401),('/api/v1/health',401),
        ('/api/account/v1/test',404)]


def base_url(value):
    parsed=urlsplit(value)
    if parsed.scheme not in ('http','https') or parsed.hostname not in HOSTS or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise ValueError('Use the Corner HTTPS origin or a loopback HTTP origin, without credentials, path or query.')
    if parsed.scheme=='http' and parsed.hostname not in ('127.0.0.1','localhost','::1'):
        raise ValueError('Public readiness checks require verified HTTPS.')
    _=parsed.port
    return value.rstrip('/')


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        return None


def fetch(origin,path,timeout=10):
    request=Request(origin+path,method='GET',headers={'User-Agent':'Corner-Readiness/1.0','Accept':'*/*'})
    opener=build_opener(HTTPSHandler(context=ssl.create_default_context()),NoRedirects())
    start=time.perf_counter()
    try:
        try: response=opener.open(request,timeout=timeout)
        except HTTPError as error: response=error
        with response:
            body=response.read(524289)
            if len(body)>524288:raise ValueError('Readiness response exceeded the fixed body bound')
            return {'status':response.code,'ms':round((time.perf_counter()-start)*1000,2),
                    'cache_control':response.headers.get('Cache-Control',''),
                    'content_type':response.headers.get('Content-Type',''),
                    'nosniff':response.headers.get('X-Content-Type-Options','')=='nosniff',
                    'body':body}
    except (OSError,URLError,ValueError):
        return {'status':0,'ms':round((time.perf_counter()-start)*1000,2),'error':'Connection, TLS or response-bound check failed'}


def probe(origin,*,samples=20,concurrency=5,reader=fetch):
    origin=base_url(origin)
    if not 1<=samples<=50 or not 1<=concurrency<=10:raise ValueError('Use 1-50 samples and 1-10 concurrent anonymous reads.')
    checks=[]
    for path,expected in CHECKS:
        item=reader(origin,path);body=item.pop('body',b'');ok=item['status']==expected
        if path.startswith('/api/') and expected==401:
            ok=ok and 'no-store' in item.get('cache_control','')
        if path=='/manifest.webmanifest' and item['status']==200:
            try:
                manifest=json.loads(body)
                ok=ok and manifest.get('display')=='standalone' and manifest.get('start_url')=='/'
                ok=ok and {i['src'] for i in manifest.get('icons',[])} >= {'/assets/corner-icon-192.png','/assets/corner-icon-512.png'}
            except (ValueError,TypeError,KeyError):ok=False
        if path.endswith('.png') and item['status']==200:
            ok=ok and body.startswith(b'\x89PNG\r\n\x1a\n')
        if origin.startswith('https:'):
            ok=ok and item.get('nosniff',False)
        checks.append({'path':path,'expected':expected,'result':'passed' if ok else 'failed',**item})
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        reads=list(pool.map(lambda _:reader(origin,'/login'),range(samples)))
    values=sorted(r['ms'] for r in reads)
    failed=sum(r['status']!=200 for r in reads)
    p95=values[math.ceil(len(values)*.95)-1]
    return {'result':'passed' if all(c['result']=='passed' for c in checks) and not failed and p95<=1500 else 'failed',
            'checked_at_utc':datetime.now(timezone.utc).isoformat(),
            'origin':origin,'checks':checks,'anonymous_http':{'samples':samples,'concurrency':concurrency,'failures':failed,
            'median_ms':round(values[len(values)//2],2),'p95_ms':round(p95,2),'maximum_ms':round(values[-1],2)},
            'performance_review': 'review_latency' if p95>1500 else 'within_initial_anonymous_http_budget',
            'scope':'Anonymous full HTTP responses only; not authenticated member, database-load or browser-interaction acceptance.',
            'odds_provider_calls':0,'payment_requests':0,'state_mutations':0,'tls_verification':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='https://coopscorner.tech')
    parser.add_argument('--samples',type=int,default=20)
    parser.add_argument('--concurrency',type=int,default=5)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    try:result=probe(args.base_url,samples=args.samples,concurrency=args.concurrency)
    except ValueError as error:parser.error(str(error))
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))
    return 0 if result['result']=='passed' else 1

if __name__=='__main__':raise SystemExit(main())

"""Bounded public HTTPS member API journey. No signup, odds fetching, betting or payment writes.

Prompts privately for an EXISTING member login, reads fixed paths, then logs out
this probe session. Never records credentials, cookies, account data or bodies.
"""
import argparse
from datetime import datetime,timezone
from getpass import getpass
import json
from http.cookies import SimpleCookie
from pathlib import Path
import time
import requests

ORIGIN='https://coopscorner.tech'
ME='/api/refresh/v1/auth/me'
LOGIN='/api/refresh/v1/auth/login'
LOGOUT='/api/refresh/v1/auth/logout'
READS=(ME,'/api/refresh/v1/billing/status','/api/refresh/v1/tracker/state',
       '/api/refresh/v1/settings','/api/refresh/v1/props','/api/refresh/v1/props/trends/options',
       '/api/v1/health','/api/v1/games?limit=100',
       '/api/v1/tools/positive_ev?limit=100','/api/v1/tools/arbitrage?limit=100',
       '/api/v1/tools/middle?limit=100','/api/v1/tools/low_hold?limit=100')

class ProbeError(Exception):pass

def journey(username,password,*,transport=None):
    """Transport injection is test-only; the production destination cannot be overridden."""
    session=requests.Session() if transport is None else transport
    session.trust_env=False
    checks=[];logged_in=False;cleanup=None
    def call(method,path,body=None):
        if (method,path) not in {('POST',LOGIN),('POST',LOGOUT)} and not (method=='GET' and path in READS):
            raise ProbeError('Request outside the fixed no-spend allowlist.')
        start=time.perf_counter()
        with session.request(method,ORIGIN+path,json=body,headers={'Origin':ORIGIN,'Accept':'application/json','User-Agent':'Corner-Member-Readiness/1.0'},
                             timeout=(5,20),allow_redirects=False,verify=True,stream=True) as response:
            raw=bytearray()
            for chunk in response.iter_content(65536):
                raw.extend(chunk)
                if len(raw)>16*1024*1024:raise ProbeError('Response exceeded the fixed body bound.')
            try:payload=json.loads(raw)
            except ValueError:raise ProbeError('A member route did not return valid JSON.') from None
            if not isinstance(payload,dict):raise ProbeError('A member route returned an unexpected response.')
            return response.status_code,response.headers,payload,round((time.perf_counter()-start)*1000,2)
    result={'result':'failed','checked_at_utc':datetime.now(timezone.utc).isoformat(),'origin':ORIGIN,'checks':checks,
            'provider_calls':0,'payment_writes':0,'signup_writes':0,'bet_writes':0,'tls_verification':True,
            'scope':'One existing member through public HTTPS APIs. Login/logout only; not browser interaction, odds freshness, predictive calibration, or concurrent load evidence.'}
    try:
        status,headers,_,ms=call('GET',ME)
        checks.append({'path':ME,'phase':'anonymous','status':status,'ms':ms})
        if status!=401 or 'no-store' not in headers.get('Cache-Control',''):raise ProbeError('Anonymous account access or cache policy failed.')
        status,headers,payload,ms=call('POST',LOGIN,{'username':username,'password':password,'remember':False})
        password=None
        if status!=200:raise ProbeError('Sign-in failed; check credentials or account access privately. No automatic retry was attempted.')
        logged_in=True
        cookie=SimpleCookie();cookie.load(headers.get('Set-Cookie',''))
        session_cookie=cookie.get('corner_session')
        if ('no-store' not in headers.get('Cache-Control','') or not session_cookie or not session_cookie['secure'] or not session_cookie['httponly'] or session_cookie['samesite'].lower()!='strict'):
            raise ProbeError('Secure session cookie or private login cache policy failed.')
        result['secure_session_cookie']=True
        user=payload.get('user') or {}
        if user.get('role')!='member':
            result.update(result='incomplete',reason='Use an active beta or friend member. An operator account cannot prove member access.')
        elif user.get('membership',{}).get('allowed') is False:
            raise ProbeError('This membership is not currently allowed to use the tools.')
        else:
            for path in READS:
                status,headers,payload,ms=call('GET',path)
                ok=status==200 and 'no-store' in headers.get('Cache-Control','')
                if path==ME:ok=ok and (payload.get('user') or {}).get('id')==user.get('id')
                if path.endswith('/billing/status'):
                    ok=ok and payload.get('payments_enabled') is False
                checks.append({'path':path,'phase':'member','status':status,'ms':ms,'result':'passed' if ok else 'failed'})
                if not ok:raise ProbeError('A member read or disabled-checkout guard failed; see the path/status only report.')
            result.update(result='passed',member_cohort=user.get('cohort'),fresh_odds_verified=False)
    except (requests.RequestException,ProbeError):
        # No exception repr: libraries can retain request bodies and cookies.
        result.update(result='failed',reason='Public member check failed. Review statuses privately; credentials and response bodies were not recorded.')
    finally:
        if logged_in:
            try:
                status,_,_,_=call('POST',LOGOUT,{})
                cleanup=status==200
                if cleanup:
                    status,_,_,_=call('GET',ME)
                    cleanup=status==401
            except (requests.RequestException,ProbeError):cleanup=False
            if not cleanup:result.update(result='failed',reason='The probe session logout check failed.')
        session.close()
        result['probe_session_logged_out']=cleanup
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('retained/release-evidence/public-member-journey.json'))
    args=parser.parse_args()
    print('Use an existing MEMBER account, not the operator. No signup, payment, odds refresh or bet changes will occur.')
    try:
        username=input('Member username: ').strip()
        password=getpass('Member password (hidden): ')
        if not username or not password:parser.error('A member username and password are required.')
        result=journey(username,password)
    except (EOFError,KeyboardInterrupt):parser.exit(1,'Cancelled.\n')
    from pipelines.recovery_probe import write_private
    write_private(args.output,result)
    print(json.dumps(result,indent=2))
    return 0 if result['result']=='passed' else 2 if result['result']=='incomplete' else 1
if __name__=='__main__':raise SystemExit(main())

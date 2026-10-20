"""Private funded-key onboarding while recurring collection stays disabled.

Exactly one fixed, documented zero-credit sports-list request. No odds, history,
ledger creation, publishing, service changes or activation approval writes.
"""
from datetime import datetime,timezone
from getpass import getpass
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time
import requests
from dotenv import dotenv_values
from corner.collection_maintenance import maintenance_lock
from corner.collection_quota import quota_headers
from corner.collection_activation import APPROVAL,STATE
from pipelines.recovery_probe import reject_collectors,write_private

ROOT=Path('/srv/corner/app')
CONFIG=Path('/srv/corner/config/collection.env')
STAGING=Path('/srv/corner/config/staging.env')
REPORT=Path('/srv/corner/collection/onboarding/quota-check.json')
URL='https://api.the-odds-api.com/v4/sports'
class OnboardingError(ValueError):pass

def quota_window(now):
    if now.tzinfo is None or now.utcoffset() is None:raise OnboardingError('Timezone-aware clock required.')
    now=now.astimezone(timezone.utc)
    start=now.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
    end=start.replace(year=start.year+1,month=1) if start.month==12 else start.replace(month=start.month+1)
    return start.isoformat(),end.isoformat()

def private_file(path):
    path=Path(path);info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_nlink!=1:
        raise OnboardingError('Private regular configuration file required.')
    if os.name!='nt' and (info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o600):
        raise OnboardingError('Configuration must be owned by this user with mode 600.')

def disabled_config(path=CONFIG,stage=STAGING):
    private_file(path);private_file(stage)
    values=dotenv_values(path);staging=dotenv_values(stage)
    if (values.get('CORNER_COLLECTION_ENABLED')!='0' or values.get('CORNER_PRIVATE_BETA')!='1'
        or staging.get('CORNER_PRIVATE_BETA')!='1' or staging.get('CORNER_REFRESH_DAILY_CAP')!='0'
        or staging.get('ODDS_API_KEY')):
        raise OnboardingError('Disabled private-beta configuration required; staging must not have a provider key.')
    return values

def verify_key(key,*,session=None,now=None):
    if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,160}',key):
        raise OnboardingError('Invalid key format. Nothing was stored.')
    session=requests.Session() if session is None else session
    session.trust_env=False
    try:
        started=time.monotonic()
        with session.get(URL,params={'apiKey':key},timeout=(5,20),allow_redirects=False,verify=True,stream=True) as response:
            raw=bytearray()
            for chunk in response.iter_content(65536):
                raw.extend(chunk)
                if time.monotonic()-started>40:raise OnboardingError('Provider response deadline exceeded.')
                if len(raw)>1024*1024:raise OnboardingError('Provider response too large.')
            if key.encode() in raw:raise OnboardingError('Credential echo refused.')
            if response.status_code!=200:raise OnboardingError('Provider key validation failed; no automatic retry.')
            headers={k.lower():v for k,v in response.headers.items()}
            used,remaining,charge=quota_headers(headers)
            if charge!=0:raise OnboardingError('Unexpected sports-list charge; stop and reconcile privately.')
            payload=json.loads(raw)
            if not isinstance(payload,list) or not payload or any(not isinstance(s,dict) or not isinstance(s.get('key'),str) for s in payload):
                raise OnboardingError('Invalid sports-list response.')
            checked=datetime.now(timezone.utc) if now is None else now
            start,end=quota_window(checked)
            return dict(result='verified_disabled_setup',quota_total=used+remaining,provider_used=used,
                provider_remaining=remaining,last_request_charge=charge,checked_at_utc=checked.isoformat(),
                quota_cycle_start_utc=start,next_quota_reset_utc=end,
                quota_reset_basis='Calendar-month UTC reset: owner dashboard and provider FAQ; not an API reset-date header.',
                subscription_started='2026-10-20',next_invoice_date='2026-11-20',
                invoice_basis='Owner-provided dashboard screenshot; independent of quota reset.',
                active_sport_keys=sum(s.get('active') is True for s in payload),
                inventory_calls=1,paid_odds_calls=0,historical_calls=0,
                worker_started=False,collector_enabled=False,live_ledger_initialized=False)
    except (requests.RequestException,ValueError,TypeError,KeyError):
        # Never print URLs/response bodies/request exceptions, which can contain the key.
        raise OnboardingError('Provider verification refused. No automatic retry or activation; inspect quota privately.') from None
    finally:session.close()

def store_key(path,key,original):
    path=Path(path);private_file(path)
    if path.read_text(encoding='utf-8')!=original:raise OnboardingError('Configuration changed during verification.')
    before=dotenv_values(path)
    if before.get('CORNER_COLLECTION_ENABLED')!='0':raise OnboardingError('Collector must remain disabled.')
    if before.get('ODDS_API_KEY') and before['ODDS_API_KEY']!=key:
        raise OnboardingError('A different key is already stored; use an explicit rotation workflow.')
    pattern=r"(?m)^[ \t]*(?:export[ \t]+)?ODDS_API_KEY[ \t]*=.*$"
    if len(re.findall(pattern,original))>1:raise OnboardingError('Ambiguous provider key configuration.')
    updated=re.sub(pattern,"ODDS_API_KEY='"+key+"'",original) if re.search(pattern,original) else original.rstrip()+"\nODDS_API_KEY='"+key+"'\n"
    fd,temporary=tempfile.mkstemp(prefix='.collection-onboarding-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as handle:
            handle.write(updated);handle.flush();os.fsync(handle.fileno())
        os.chmod(temporary,0o600)
        expected=dict(before);expected['ODDS_API_KEY']=key
        if dict(dotenv_values(temporary))!=expected:raise OnboardingError('Configuration round-trip refused.')
        if path.read_text(encoding='utf-8')!=original:raise OnboardingError('Configuration changed; refusing replacement.')
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)

def preflight():
    if os.name!='posix' or Path.cwd().resolve()!=ROOT:raise OnboardingError('Run on the VPS from /srv/corner/app.')
    parent=CONFIG.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or stat.S_ISLNK(parent.st_mode) or parent.st_uid!=os.geteuid() or parent.st_mode&0o077:
        raise OnboardingError('Private owner-controlled configuration directory required.')
    values=disabled_config()
    if STATE.exists() or STATE.is_symlink():raise OnboardingError('Live ledger already exists. Use audited status/reconciliation; do not reinitialize.')
    if APPROVAL.exists() and json.loads(APPROVAL.read_text(encoding='utf-8')).get('approved') is True:
        raise OnboardingError('Activation approval already exists; stop and review.')
    listing=subprocess.check_output(['systemctl','list-unit-files','--type=service,timer','--no-legend','--no-pager'],text=True,stderr=subprocess.DEVNULL,timeout=15)
    reject_collectors(listing)
    return values

def main():
    os.umask(0o077)
    try:
        step='disabled_configuration_preflight'
        values=preflight()
        key=values.get('ODDS_API_KEY') or getpass('Funded Odds API key (hidden; never paste into chat): ').strip()
        with maintenance_lock(exclusive=True):
            preflight()
            original=CONFIG.read_text(encoding='utf-8')
            step='zero_credit_provider_verification'
            result=verify_key(key)
            step='private_disabled_key_storage'
            store_key(CONFIG,key,original)
            step='private_evidence_record'
            if any(p.is_symlink() for p in (REPORT,REPORT.parent,REPORT.parent.parent)):
                raise OnboardingError('Evidence symlink refused.')
            REPORT.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            write_private(REPORT,result)
        print(json.dumps(result,indent=2))
        print('Key stored only in private disabled collection.env. Staging unchanged. No live ledger or activation created.')
        print('Next: reviewed paused ledger binding, then a separately capped odds/publication smoke test.')
        return 0
    except (Exception,KeyboardInterrupt):
        print(json.dumps({'result':'refused','step':step,'worker_started':False,'automatic_retry':False,'action':'Preserve private evidence; inspect configuration without displaying secrets.'}))
        return 1
if __name__=='__main__':raise SystemExit(main())

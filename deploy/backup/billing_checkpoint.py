"""Billing checkpoint metadata and recovery gates. Standard library only."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3

BILLING_PATH = 'config/billing.json'
EXPECTED_REFERENCE = '/srv/corner/config/billing.json'
BILLING_TABLES = ('beta_members','beta_invites','beta_trials','beta_payment_requests','beta_payment_receipts','beta_audit','beta_friend_rates','beta_invitation_pages','beta_invitation_acceptances','beta_invitation_feedback')


def billing_reference(staging):
    """Only the reviewed standard path is covered; never silently omit another."""
    matches=[]
    for line in Path(staging).read_text(encoding='utf-8').splitlines():
        stripped=line.strip()
        if re.match(r'(?:export\s+)?CORNER_BILLING_CONFIG\s*=',stripped):
            matches.append(stripped)
    if not matches:
        return False
    if len(matches)!=1:
        raise ValueError('Ambiguous billing configuration reference')
    value=matches[0].split('=',1)[1].strip()
    if value in ('',"''",'""'):
        return False
    if value not in (EXPECTED_REFERENCE,"'"+EXPECTED_REFERENCE+"'",'"'+EXPECTED_REFERENCE+'"'):
        raise ValueError('Billing configuration outside reviewed backup coverage')
    return True


def billing_summary(path):
    raw=Path(path).read_bytes()
    config=json.loads(raw)
    if not isinstance(config,dict):raise ValueError('Billing JSON object required')
    for field in ('payments_enabled','memo_reviewed','receive_test_passed','manual_review_ready'):
        if type(config.get(field)) is not bool:raise ValueError('Explicit billing gates required')
    if not isinstance(config.get('terms_version'),str) or not config['terms_version']:
        raise ValueError('Billing terms version missing')
    receivers=config.get('receiving')
    if not isinstance(receivers,dict) or set(receivers)!={'XRP','HBAR','XLM'}:
        raise ValueError('Native billing receivers incomplete')
    for receiver in receivers.values():
        if not isinstance(receiver,dict) or set(receiver)!={'address','memo'} or not isinstance(receiver['address'],str) or not receiver['address']:
            raise ValueError('Billing receiving data incomplete')
        if receiver['memo'] is not None and not isinstance(receiver['memo'],str):raise ValueError('Invalid billing memo')
    return {'present':True,'path':BILLING_PATH,'sha256':hashlib.sha256(raw).hexdigest(),
            'terms_version':config['terms_version'],
            **{key:config[key] for key in ('payments_enabled','memo_reviewed','receive_test_passed','manual_review_ready')}}


def snapshot_billing(base,data,*,required,copy):
    needed=required or billing_reference(data/'config/staging.env')
    source=base/BILLING_PATH
    if not source.exists() and not source.is_symlink():
        if needed:raise ValueError('Required billing configuration missing')
        return {'present':False,'path':BILLING_PATH}
    copy(source,data/BILLING_PATH)
    return billing_summary(data/BILLING_PATH)


def account_billing_summary(path):
    result={}
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for name in BILLING_TABLES:
            if name not in tables:continue
            h=hashlib.sha256();count=0
            columns=[row[1] for row in db.execute('PRAGMA table_info('+name+')')]
            h.update(json.dumps(columns,separators=(',',':')).encode())
            for row in db.execute('SELECT * FROM '+name+' ORDER BY rowid'):
                h.update(json.dumps(list(row),ensure_ascii=True,separators=(',',':')).encode()+b'\n')
                count+=1
            result[name]={'rows':count,'sha256':h.hexdigest()}
    return result


def recover_billing(root,manifest):
    """Verify original archived bytes first; disable only the recovered copy."""
    config_path=root/BILLING_PATH
    expected=manifest.get('billing')
    if 'account_billing' in manifest and account_billing_summary(root/'accounts.sqlite3')!=manifest['account_billing']:
        raise ValueError('Recovered billing account records differ')
    if expected is None:
        if config_path.exists() or billing_reference(root/'config/staging.env'):
            raise ValueError('Billing configuration lacks checkpoint evidence')
        return False  # Old pre-billing archives remain verifiable.
    if not isinstance(expected,dict):raise ValueError('Invalid billing checkpoint metadata')
    present=config_path.exists()
    if type(expected.get('present')) is not bool or expected.get('path')!=BILLING_PATH or present!=expected['present']:
        raise ValueError('Billing checkpoint coverage differs')
    if not present:
        if billing_reference(root/'config/staging.env'):raise ValueError('Referenced billing configuration absent')
        return False
    if billing_summary(config_path)!=expected:
        raise ValueError('Recovered billing configuration differs')
    if 'account_billing' not in manifest or account_billing_summary(root/'accounts.sqlite3')!=manifest['account_billing']:
        raise ValueError('Recovered billing account records differ')
    config=json.loads(config_path.read_text(encoding='utf-8'))
    config.update(payments_enabled=False,manual_review_ready=False,receive_test_passed=False)
    config_path.write_text(json.dumps(config,indent=2)+'\n',encoding='utf-8')
    # No live file, account, invoice, receipt or founder flag is changed.
    return True

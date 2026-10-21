"""Private invitation previews and recorded welcome agreements. No collection or billing."""
import json
import re
import time
from corner import beta_access as beta, beta_terms

VERSION = 'family-welcome-2026-10-v1'
TOKEN = re.compile(r'[A-Za-z0-9_-]{20,200}\Z')

def lookup(db, token, *, claimed=False):
    if not isinstance(token,str) or not TOKEN.fullmatch(token):
        beta.fail('This invitation is unavailable. Ask your host for a new link.',status=404)
    row=db.execute('SELECT * FROM beta_invites WHERE token_hash=?',(beta.digest(token),)).fetchone()
    if not row or row['revoked'] or (not claimed and (row['redeemed_by'] or row['expires_at']<=time.time())):
        beta.fail('This invitation is unavailable. Ask your host for a new link.',status=404)
    return row

def offer(db, token, user=None):
    row=lookup(db,token,claimed=True)
    if row['redeemed_by']:
        if not user or user['id']!=row['redeemed_by']:beta.fail('Sign in to the account that claimed this invitation.',status=401)
    elif row['expires_at']<=time.time():beta.fail('Invitation expired.',status=404)
    cohort=beta.invite_cohort(db,row)
    family=cohort=='family'
    if not family and time.time()>=beta_terms.BETA_END:
        beta.fail('This beta has ended.',status=410)
    friend=cohort=='friend'
    paid=row['access_kind']=='paid_beta'
    trial_available=beta_terms.trial_available(time.time())
    return dict(cohort=cohort,claimed=bool(row['redeemed_by']),paid=paid,version=VERSION,terms_version=beta_terms.VERSION,
        expires_at=row['expires_at'],username=row['username_key'],trial_available=trial_available,
        title='A brother at the table' if family else 'The inner circle' if friend else 'The founding table',
        access=('Permanent complimentary access to all available tools, including standard and live when available. No trial or payment required.' if family else 'Complimentary beta access through November 20, 2026.' if friend else
                'Your verified paid beta access runs through November 20, 2026.' if paid else
                'Seven days free when your trial is activated. Then choose whether to pay $50 for the remaining beta.' if trial_available else
                'A full seven-day trial is no longer available. Contact your host before joining.'),
        pricing=('Always free. $0 for standard and live; no subscription or recurring charge.' if family else '$25/month standard or $50/month live when available, both locked in after release.' if friend else
                 '$50/month pregame standard locked in after release.' if paid else
                 'Paying the beta fee locks $50/month pregame standard after release. Otherwise the launch rate is $125/month.'),
        end_label='No expiry' if family else 'November 20, 2026 at 11:59 p.m. Central')

def wrap(db, actor, token):
    beta.require_operator(db,actor)
    row=lookup(db,token)
    db.execute('INSERT OR IGNORE INTO beta_invitation_pages VALUES(?)',(row['id'],))
    beta.audit(db,actor,'invitation_link',row['id'],VERSION)
    return 'https://coopscorner.tech/invite#'+token

def accept(db, token, body):
    current=offer(db,token)
    if body.get('version')!=VERSION or body.get('terms_version')!=beta_terms.VERSION or body.get('eligible') is not True or body.get('agree') is not True:
        beta.fail('Review and accept the current terms and eligibility statement.',status=400)
    row=lookup(db,token)
    db.execute('INSERT OR IGNORE INTO beta_invitation_acceptances(invite_id,version,terms_version,accepted_at,offer_json) VALUES(?,?,?,?,?)',
        (row['id'],VERSION,beta_terms.VERSION,time.time(),json.dumps(current,sort_keys=True)))
    return {'accepted':True}

def require_acceptance(db, invite):
    if db.execute('SELECT 1 FROM beta_invitation_pages WHERE invite_id=?',(invite['id'],)).fetchone():
        if not db.execute('SELECT 1 FROM beta_invitation_acceptances WHERE invite_id=? AND version=? AND terms_version=?',(invite['id'],VERSION,beta_terms.VERSION)).fetchone():
            beta.fail('Open your invitation link and accept the welcome terms before creating your account.','welcome_required')

def feedback(db, token, body, user):
    row=lookup(db,token,claimed=True)
    if row['redeemed_by']:
        if not user or user['id']!=row['redeemed_by']:
            beta.fail('Sign in to the account that claimed this invitation.',status=401)
    elif row['expires_at']<=time.time():beta.fail('Invitation expired.',status=404)
    category=body.get('category')
    if category not in ('bug','feature','data','question','other'):beta.fail('Choose a feedback type.',status=400)
    values=[]
    for field,limit in (('title',120),('message',4000)):
        text=body.get(field)
        if not isinstance(text,str) or not 1<=len(text.strip())<=limit or any(ord(c)<32 and c not in '\n\t' for c in text):
            beta.fail('Enter a short title and a description of up to 4,000 characters.',status=400)
        values.append(text.strip())
    if db.execute('SELECT count(*) FROM beta_invitation_feedback WHERE invite_id=? AND created_at>?',(row['id'],time.time()-3600)).fetchone()[0]>=5:
        beta.fail('Please wait before sending more feedback.',status=429)
    cursor=db.execute('INSERT INTO beta_invitation_feedback(invite_id,user_id,category,title,message,created_at) VALUES(?,?,?,?,?,?)',
        (row['id'],user['id'] if user else None,category,*values,time.time()))
    return {'received':True,'reference':cursor.lastrowid}

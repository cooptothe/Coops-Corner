"""Bounded rescheduling after an audited, zero-charge transport recovery."""
import json
from corner.credit_governor import Refused


def release_zero_charge_recoveries(g, now):
    """Run only immediately after fresh offline quota reconciliation/resume.

    Retain every attempt and its cost. Archive released quarantine evidence.
    Never publish a response, refund a reservation or bypass purchase gates.
    """
    with g.transaction() as db:
        g._offline(db,now)
        latest=db.execute('SELECT action FROM quota_audit ORDER BY id DESC LIMIT 1').fetchone()
        binding=g._binding(db,now)
        if not latest or latest[0]!='resume' or not 0<=now.timestamp()-binding['checked']<300:
            raise Refused('Fresh offline reconciliation and resume required for retry review')
        if db.execute("SELECT 1 FROM attempts WHERE state!='settled' UNION ALL SELECT 1 FROM quota_inventory WHERE state!='settled'").fetchone():
            raise Refused('Unresolved requests prohibit retry review')
        # A zero cost must be proved by an actual settlement audit, not merely
        # a quarantine label or missing response headers.
        proved=set()
        responses=set()
        failed_settlement=set()
        for action,raw in db.execute("SELECT action,detail FROM quota_audit WHERE action IN ('reconcile','odds-response','request-failed')"):
            detail=json.loads(raw)
            if action=='reconcile' and detail.get('cycle')==binding['cycle_id']:
                proved.update(s['token'] for s in detail.get('settlements',[])
                              if s.get('kind')=='attempts' and type(s.get('actual')) is int and s['actual']==0)
            elif action=='odds-response':responses.add(detail.get('token'))
            elif action=='request-failed' and detail.get('phase')!='transport':failed_settlement.add(detail.get('token'))
        db.execute('CREATE TABLE IF NOT EXISTS transport_quarantine_archive(job_key TEXT,token TEXT,created REAL,code TEXT,detail TEXT,released REAL,retry_after REAL,PRIMARY KEY(job_key,token))')
        released=[]
        for row in db.execute("SELECT q.*,a.state,a.actual AS settled_actual,a.cycle_id FROM collection_quarantine q JOIN attempts a ON a.token=q.token AND a.job_key=q.job_key WHERE q.code='recovered_snapshot_failure'").fetchall():
            detail=json.loads(row['detail'])
            if (detail.get('basis')!='operator_accepted_provider_total_delta' or
                type(detail.get('actual')) is not int or detail['actual']!=0 or
                detail.get('response_audit_at') is not None or
                row['state']!='settled' or row['settled_actual']!=0 or row['cycle_id']!=binding['cycle_id'] or
                row['token'] not in proved or row['token'] in responses or row['token'] in failed_settlement):
                continue
            previous=db.execute('SELECT count(*) FROM transport_quarantine_archive WHERE job_key=?',(row['job_key'],)).fetchone()[0]
            delay=min(3600,300*2**min(previous,4))
            retry_after=row['created']+delay
            db.execute('INSERT INTO transport_quarantine_archive VALUES(?,?,?,?,?,?,?)',
                tuple(row[k] for k in ('job_key','token','created','code','detail'))+(now.timestamp(),retry_after))
            db.execute('INSERT INTO collection_retry_cooldowns VALUES(?,?) ON CONFLICT(job_key) DO UPDATE SET retry_after=max(retry_after,excluded.retry_after)',(row['job_key'],retry_after))
            db.execute('DELETE FROM collection_quarantine WHERE job_key=? AND token=?',(row['job_key'],row['token']))
            db.execute("UPDATE jobs SET state='idle',last_error='',next_due=max(next_due,?) WHERE key=?",(retry_after,row['job_key']))
            released.append({'job_key':row['job_key'],'token':row['token'],'retry_after':retry_after})
        g._audit(db,now,'zero-charge-retry-review','Settled zero-charge transport recoveries; archived evidence and bounded cooldown',{'released':released})
    return released

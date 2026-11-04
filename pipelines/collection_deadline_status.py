"""Read-only deadline status. No provider requests or ledger mutation."""
import json,sqlite3
from corner.collection_activation import STATE
def main():
    with sqlite3.connect(STATE.resolve().as_uri()+'?mode=ro',uri=True) as db:
        row=db.execute('SELECT payload FROM deadline_pacing_state WHERE id=1').fetchone()
        if not row:
            print(json.dumps({'state':'awaiting_first_deadline_plan','provider_calls':0}));return
        value=json.loads(row[0]);periods=value.pop('interval_seconds',{})
        from datetime import datetime,timezone
        from corner.deadline_pacing import END
        now=datetime.now(timezone.utc)
        value['status_age_seconds']=round(now.timestamp()-value['checked_at'],1)
        if now>=END:value['state']='deadline_closed'
        if value.get('remaining')==0:value['state']='quota_exhausted' 
        value['scheduled_scopes']=len(periods)
        value['fastest_interval_seconds']=min(periods.values(),default=None)
        value['slowest_interval_seconds']=max(periods.values(),default=None)
        latest=db.execute('SELECT b.used FROM quota_bindings b JOIN cycles c ON c.id=b.cycle_id WHERE c.starts<=? AND c.ends>?',(now.timestamp(),now.timestamp())).fetchone()
        if latest:
            value['provider_reported_used']=latest[0]
            value['provider_reported_remaining']=15000000-latest[0]
            if latest[0]>=15000000:value['state']='quota_exhausted'
        value['window']='06:00–24:00 Central; overnight tennis/soccer only within 2h or live'
        value['provider_calls']=0
        print(json.dumps(value,indent=2))
if __name__=='__main__':main()

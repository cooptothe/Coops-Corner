"""Offline collection rehearsal. No HTTP client, API key, or feed publication.

This first deployment validates the control plane. A live transport/discovery,
PostgreSQL/props publication adapter and feed status integration are later gates.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import time

from corner.collection_policy import plan, parse
from corner.credit_governor import Governor, Refused


def tick(governor,manifest,now,owner,transport):
    if not governor.acquire(owner,now):
        return {'mode':'simulation','state':'another_worker','executed':0}
    jobs=plan(now,manifest['active_sport_keys'],manifest['events'])
    executed=0;deferred={}
    for job in jobs:
        if not governor.ready(job,now): continue
        try:
            governor.prepare_due(job,owner,now)
            token=governor.claim(job,owner,now)
        except Refused as error:
            name=str(error)
            deferred[name]=deferred.get(name,0)+1
            continue
        try:
            status,payload,headers=transport(job,now)
            governor.finish(job,token,owner,now,headers,payload,status)
        except Exception:
            # No automatic replay after a timeout, malformed payload or uncertain charge.
            governor.unknown(token,owner,now)
            deferred['uncertain_response']=deferred.get('uncertain_response',0)+1
        executed+=1
    return {'mode':'simulation','provider_calls':0,'feed_publication':False,
            'planned_jobs':len(jobs),'executed':executed,'deferred':deferred,
            'ledger':governor.status()}


def fixture_transport(manifest):
    responses=manifest.get('responses',{})
    def run(job,now):
        value=responses.get(job.key,{})
        return (value.get('http_status',200),value.get('events',[]),
                value.get('headers',{'x-requests-last':str(job.cost),
                                     'x-requests-remaining':'15000000'}))
    return run


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True)
    parser.add_argument('--state',required=True,help='Separate simulation SQLite path, never account DB')
    parser.add_argument('--now',help='Optional fixed UTC timestamp for a single rehearsal tick')
    parser.add_argument('--loop',action='store_true')
    args=parser.parse_args()
    if args.loop and args.now: parser.error('--now and --loop cannot be combined')
    manifest=json.loads(Path(args.manifest).read_text(encoding='utf-8'))
    if manifest.get('format')!='corner.collection_simulation/1':
        parser.error('An explicitly labeled simulation manifest is required')
    state=Path(args.state)
    if 'simulation' not in state.name:
        parser.error('State filename must include simulation to distinguish fake quota accounting')
    governor=Governor(state)
    owner=secrets.token_hex(16)
    try:
        governor.configure_cycle('simulation-'+manifest['cycle_id'],parse(manifest['cycle_start']),parse(manifest['cycle_end']))
        while True:
            now=parse(args.now) if args.now else datetime.now(timezone.utc)
            print(json.dumps(tick(governor,manifest,now,owner,fixture_transport(manifest)),sort_keys=True),flush=True)
            if not args.loop: break
            time.sleep(5)
    finally:
        try: governor.release(owner)
        finally: governor.close()


if __name__=='__main__': main()

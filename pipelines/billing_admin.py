"""Server-only manual payment review. Never sends funds or fetches rates."""
import argparse
import json
from pathlib import Path
from corner import auth, beta_access
from corner.beta_invoices import BetaInvoices
from corner.tracker_store import TrackerStore, TrackerError


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',required=True)
    parser.add_argument('--operator',required=True)
    commands=parser.add_subparsers(dest='command',required=True)
    for name in ('inspect','approve'):
        p=commands.add_parser(name);p.add_argument('request_id')
        if name=='approve':p.add_argument('--review',required=True,help='Private JSON with independently reviewed receipt details')
    args=parser.parse_args()
    if not Path(args.db).is_file():parser.error('Use the existing account database.')
    store=TrackerStore(args.db)
    try:
        operator=store.user_by_key(auth.clean_username(args.operator)[1])
        if not operator:raise TrackerError('Operator not found.',403)
        beta_access.require_operator(store._db,operator['id'])
        invoices=BetaInvoices(store)
        if args.command=='approve':
            review=json.loads(Path(args.review).read_text(encoding='utf-8'))
            expected={'evidence','delivered_base_units','destination','memo','received_at','transfer_index'}
            if not isinstance(review,dict) or set(review)!=expected:
                raise TrackerError('Review JSON must contain exact documented fields.',400)
            print(json.dumps(invoices.approve(operator['id'],args.request_id,**review)))
        else:
            row=store._db.execute('SELECT * FROM beta_payment_requests WHERE id=?',(args.request_id,)).fetchone()
            if not row:raise TrackerError('Request not found.',404)
            print(json.dumps(dict(row),indent=2))
    except (TrackerError,ValueError,OSError) as error:
        parser.exit(1,str(error)+'\n')
    finally:store.close()

if __name__=='__main__':main()

"""Server-only manual payment review. Never sends funds or fetches rates."""
import argparse
import json
from pathlib import Path
from corner import auth, beta_access
from corner.billing_config import checkout_config
from corner.beta_invoices import BetaInvoices
from corner.tracker_store import TrackerStore, TrackerError


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',required=True)
    parser.add_argument('--operator',required=True)
    parser.add_argument('--env-file',help='Existing private environment file for reviewed checkout configuration')
    commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('pending')
    for name in ('inspect','approve','quote'):
        p=commands.add_parser(name);p.add_argument('request_id')
        if name=='quote':p.add_argument('--rate',required=True,help='Private JSON: usd_per_coin string, observed_at Unix seconds, source')
        if name=='approve':p.add_argument('--review',required=True,help='Private JSON with independently reviewed receipt details')
    args=parser.parse_args()
    if not Path(args.db).is_file():parser.error('Use the existing account database.')
    if args.env_file:
        if not Path(args.env_file).is_file():parser.error('Environment file not found.')
        from dotenv import load_dotenv
        load_dotenv(args.env_file,override=True)
    store=TrackerStore(args.db)
    try:
        operator=store.user_by_key(auth.clean_username(args.operator)[1])
        if not operator:raise TrackerError('Operator not found.',403)
        beta_access.require_operator(store._db,operator['id'])
        invoices=BetaInvoices(store)
        if args.command=='pending':
            rows=store._db.execute("SELECT r.id,u.username,r.asset,r.state,r.created_at,r.expires_at FROM beta_payment_requests r JOIN users u ON u.id=r.user_id WHERE r.state IN ('requested','quoted','submitted') ORDER BY r.created_at").fetchall()
            print(json.dumps([dict(row) for row in rows],indent=2))
        elif args.command=='quote':
            config=checkout_config()
            if config is None:raise TrackerError('Reviewed checkout configuration is disabled or incomplete.',409)
            rate=json.loads(Path(args.rate).read_text(encoding='utf-8'))
            if not isinstance(rate,dict) or set(rate)!= {'usd_per_coin','observed_at','source'}:
                raise TrackerError('Rate JSON must contain usd_per_coin, observed_at and source.',400)
            invoices.quote(operator['id'],args.request_id,receiving=config,**rate)
            print('Time-limited quote prepared; member can review it in Account.')
        elif args.command=='approve':
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

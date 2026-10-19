"""Server-only beta administration. Never exposes an HTTP bootstrap endpoint."""
import argparse
import os
from datetime import datetime,timezone
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError

from corner import auth, beta_access as beta, invitation_welcome as welcome
from corner.tracker_store import TrackerStore, TrackerError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, help='Existing private account SQLite file')
    parser.add_argument('--operator', help='Explicit bootstrapped operator username')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status')
    bootstrap = commands.add_parser('bootstrap')
    bootstrap.add_argument('username')
    for name in ('invite', 'grant'):
        p = commands.add_parser(name)
        p.add_argument('username', **({'nargs':'?'} if name=='invite' else {}))
        p.add_argument('--kind', choices=('preview','paid_beta'), required=True)
        p.add_argument('--cohort', choices=('beta','friend'), default='beta')
        p.add_argument('--evidence', required=True,
                       help='Preview reason or operator-verified receipt reference; no secrets')
        if name == 'invite':
            p.add_argument('--hours', type=int, default=48)
    p = commands.add_parser('beta-codes')
    p.add_argument('--count',type=int,default=1)
    p.add_argument('--hours',type=int,default=168)
    p.add_argument('--evidence',required=True)
    p = commands.add_parser('friend-codes')
    p.add_argument('--count',type=int,default=5)
    p.add_argument('--hours',type=int,default=168)
    p.add_argument('--evidence',required=True)
    p = commands.add_parser('move-friend')
    p.add_argument('username')
    p.add_argument('--evidence',required=True)
    p = commands.add_parser('start-trial')
    p.add_argument('username')
    p = commands.add_parser('state')
    p.add_argument('username')
    p.add_argument('value', choices=('active','suspended','closed'))
    p = commands.add_parser('revoke')
    p.add_argument('invite_id')
    args = parser.parse_args()
    if not os.path.isfile(args.db):
        parser.error('Use an existing account database; no new file will be created.')
    friend_codes=[]
    issued_invite=None
    store = TrackerStore(args.db)
    try:
        with store._lock:
            db = store._db
            db.execute('BEGIN IMMEDIATE')
            try:
                if args.command == 'bootstrap':
                    beta.bootstrap(db, auth.clean_username(args.username)[1])
                    print('Operator assigned explicitly. Sign in again; no member seat consumed.')
                elif args.command == 'status':
                    print(f'Beta places occupied or reserved: {beta.occupied(db)}/{beta.LIMIT}')
                    print(f'Friend places occupied or reserved: {beta.occupied(db,cohort="friend")}/{beta.FRIEND_LIMIT}')
                    for row in db.execute('SELECT u.username, m.role, m.state, m.access_kind, m.founder, m.cohort FROM users u LEFT JOIN beta_members m ON u.id=m.user_id ORDER BY u.username_key'):
                        print('\t'.join(str(x) if x is not None else 'not enrolled' for x in row))
                else:
                    if not args.operator:
                        parser.error('--operator is required for access mutations')
                    operator = db.execute('SELECT id FROM users WHERE username_key=?', (auth.clean_username(args.operator)[1],)).fetchone()
                    if not operator:
                        beta.fail('Operator account not found.')
                    actor = operator[0]
                    beta.require_operator(db, actor)
                    if args.command == 'beta-codes':
                        friend_codes=beta.issue_beta_codes(db,actor,count=args.count,hours=args.hours,evidence=args.evidence)
                    elif args.command == 'friend-codes':
                        friend_codes=beta.issue_friend_codes(db,actor,count=args.count,hours=args.hours,evidence=args.evidence)
                    elif args.command == 'invite':
                        invite_id, token = beta.issue(db, actor, auth.clean_username(args.username)[1] if args.username else '', hours=args.hours, access_kind=args.kind, evidence=args.evidence, cohort=args.cohort, unbound=not bool(args.username))
                        issued_invite=(invite_id,token,welcome.wrap(db,actor,token))
                    elif args.command == 'grant':
                        beta.grant(db, actor, auth.clean_username(args.username)[1], args.kind, args.evidence, cohort=args.cohort)
                        print('Existing account granted access. Sign in again.')
                    elif args.command == 'move-friend':
                        beta.move_friend(db,actor,auth.clean_username(args.username)[1],args.evidence)
                        print('Moved to a friend place; beta place released and sessions revoked. Locked rates recorded.')
                    elif args.command == 'start-trial':
                        started = beta.start_trial(db, actor, auth.clean_username(args.username)[1])
                        print(f'Immutable trial start (Unix seconds): {started}')
                    elif args.command == 'state':
                        beta.state(db, actor, auth.clean_username(args.username)[1], args.value)
                        print('Member state updated; existing sessions revoked.')
                    else:
                        beta.revoke(db, actor, args.invite_id)
                        print('Unused invitation revoked.')
                for _,code in friend_codes:welcome.wrap(db,actor,code)
                db.execute('COMMIT')
            except BaseException:
                db.execute('ROLLBACK')
                raise
            if issued_invite:
                print(f'Invitation ID: {issued_invite[0]}\nInvitation code (shown once): {issued_invite[1]}\nPrivate link: {issued_invite[2]}')
            for index,(invite_id,code) in enumerate(friend_codes,1):
                expires=db.execute('SELECT expires_at FROM beta_invites WHERE id=?',(invite_id,)).fetchone()[0]
                try:
                    label=datetime.fromtimestamp(expires,ZoneInfo('America/Chicago')).strftime('%b %d, %Y %I:%M %p Central')
                except ZoneInfoNotFoundError:
                    label=datetime.fromtimestamp(expires,timezone.utc).strftime('%b %d, %Y %I:%M %p UTC')
                label_pool='Beta' if args.command=='beta-codes' else 'Friend'
                print(f'{label_pool} {index} | ID: {invite_id} | Expires: {label}\nCode (shown once): {code}\nPrivate link: https://coopscorner.tech/invite#{code}')
            if friend_codes:print('Each code reserves one place in its own pool and works once with a new chosen username. Store privately and share one code per friend.')
    except (TrackerError, auth.AuthError) as exc:
        parser.exit(1, str(exc)+'\n')
    finally:
        store.close()


if __name__ == '__main__':
    main()

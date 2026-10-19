"""Wrap existing codes privately without creating extra reservations; review feedback."""
import argparse
from getpass import getpass
from pathlib import Path
from corner import auth,beta_access,invitation_welcome as welcome
from corner.tracker_store import TrackerStore,TrackerError

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',required=True)
    parser.add_argument('--operator',required=True)
    parser.add_argument('action',choices=('link','friends','feedback'))
    args=parser.parse_args()
    if not Path(args.db).is_file():parser.error('Use an existing account database.')
    token=getpass('Existing invitation code (hidden): ') if args.action=='link' else None
    store=TrackerStore(args.db)
    friend_tokens=[]
    try:
        if args.action=='friends':
            import time
            # Gather secrets before the write transaction; never hold a database lock at a prompt.
            count=store._db.execute("SELECT count(*) FROM beta_invites WHERE cohort='friend' AND revoked=0 AND redeemed_by IS NULL AND expires_at>?",(time.time(),)).fetchone()[0]
            if count:
                print(f'{count} live friend invitations already reserve places. Enter each saved code privately; no new places will be created.')
                friend_tokens=[getpass(f'Existing friend code {i+1}/{count} (hidden): ') for i in range(count)]
                if len(set(friend_tokens))!=count:raise TrackerError('Enter each distinct code once; no links changed.',400)

        with store._lock:
            db=store._db
            db.execute('BEGIN IMMEDIATE')
            try:
                row=db.execute('SELECT id FROM users WHERE username_key=?',(auth.clean_username(args.operator)[1],)).fetchone()
                if not row:raise TrackerError('Operator not found.',403)
                beta_access.require_operator(db,row[0])
                if args.action=='friends':
                    if not friend_tokens:
                        if beta_access.occupied(db,cohort='friend'):
                            raise TrackerError('Friends are already enrolled; no unused invitations to prepare. No new codes created.',409)
                        friend_tokens=[code for _,code in beta_access.issue_friend_codes(db,row[0],count=5,evidence='Owner requested five family invitations')]
                    for code in friend_tokens:
                        if welcome.lookup(db,code)['cohort']!='friend':raise TrackerError('Use only the existing friend codes.',400)
                    result='\n\n'.join(f'Friend {i+1} private link: '+welcome.wrap(db,row[0],code) for i,code in enumerate(friend_tokens))
                elif args.action=='link':result=welcome.wrap(db,row[0],token)
                else:
                    result='\n'.join(str(dict(r)) for r in db.execute('SELECT id,invite_id,user_id,category,title,message,created_at FROM beta_invitation_feedback ORDER BY id DESC LIMIT 100')) or 'No feedback yet.'
                db.execute('COMMIT')
            except BaseException:db.execute('ROLLBACK');raise
        print(result)
    except (EOFError,KeyboardInterrupt):parser.exit(1,'Cancelled; no pending changes committed.\n')
    except TrackerError as error:parser.exit(1,str(error)+'\n')
    finally:store.close()
if __name__=='__main__':main()

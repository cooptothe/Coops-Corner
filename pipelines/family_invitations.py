"""Operator-only issuance of two brother links, with a private reusable receipt."""
import argparse
import json
import os
from pathlib import Path
from corner import beta_access as beta, invitation_welcome as welcome
from corner.tracker_store import TrackerStore, TrackerError


def prepare(store, output):
    output=Path(output)
    if output.is_symlink():raise TrackerError('Private invitation receipt cannot be a symlink.',400)
    with store._lock:
        db=store._db
        db.execute('BEGIN IMMEDIATE')
        created=False
        try:
            owners=db.execute("SELECT user_id FROM beta_members WHERE role='admin' AND state='active'").fetchall()
            if len(owners)!=1:raise TrackerError('Exactly one active server operator is required.',403)
            actor=owners[0][0];beta.require_operator(db,actor)
            if output.exists():
                if os.name=='posix' and output.stat().st_mode & 0o077:
                    raise TrackerError('Invitation receipt must be private (mode 600).',400)
                records=json.loads(output.read_text(encoding='utf-8'))
                if not isinstance(records,list) or len(records)!=2:raise TrackerError('Invalid saved family invitation receipt.',400)
                for record in records:
                    row=welcome.lookup(db,record['token'],claimed=True)
                    if row['id']!=record['id'] or beta.invite_cohort(db,row)!='family':
                        raise TrackerError('Saved family invitations differ; no new codes created.',409)
            else:
                records=[{'id':ident,'token':code} for ident,code in beta.issue_family_codes(
                    db,actor,count=2,hours=168,evidence='Owner requested permanent free standard/live access for two brothers')]
                for record in records:welcome.wrap(db,actor,record['token'])
                fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                created=True
                with os.fdopen(fd,'w',encoding='utf-8') as stream:
                    json.dump(records,stream);stream.write('\n');stream.flush();os.fsync(stream.fileno())
            db.execute('COMMIT')
            return records
        except BaseException:
            db.execute('ROLLBACK')
            if created:output.unlink()
            raise


def main():
    os.umask(0o077)
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',required=True);p.add_argument('--output',required=True)
    a=p.parse_args()
    if not Path(a.db).is_file():p.error('Use the existing account database.')
    store=TrackerStore(a.db)
    try:
        records=prepare(store,a.output)
        for n,record in enumerate(records,1):
            print(f"Brother {n} private link: https://coopscorner.tech/invite#{record['token']}")
        print('Each link works once. Choose a username at signup. Redeem within seven days; the resulting membership stays free permanently, including live when available.')
        print('Private link receipt saved. Re-running this command shows the same links, without reserving more places.')
    except (TrackerError,ValueError,KeyError,OSError) as error:
        p.exit(1,str(error)+'\n')
    finally:store.close()


if __name__=='__main__':main()

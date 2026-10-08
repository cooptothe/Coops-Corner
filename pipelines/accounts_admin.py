"""Owner tools for accounts: list them and reset a forgotten password.

    python -m pipelines.accounts_admin list
    python -m pipelines.accounts_admin reset-password USERNAME

There is no email, so a forgotten password is reset by whoever runs the app. The new password is typed
at a hidden prompt (never on the command line), and every session the account had is signed out.
"""
import argparse
import getpass
import sys

from corner import auth
from corner.tracker_store import TrackerError, TrackerStore
from pipelines.accounts import DB_PATH


def run(argv, store, ask=getpass.getpass, out=print):
    parser = argparse.ArgumentParser(prog='accounts_admin', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('list', help='show every account')
    reset = commands.add_parser('reset-password', help='set a new password for an account')
    reset.add_argument('username')
    args = parser.parse_args(argv)

    if args.command == 'list':
        users = store.list_users()
        for user in users:
            out(f"{user['username']}\tcreated {user['created_at'][:10]}")
        out(f'{len(users)} account(s)')
        return 0

    try:
        _, key = auth.clean_username(args.username)
    except auth.AuthError:
        out(f'No account named {args.username!r}.')
        return 1
    user = store.user_by_key(key)
    if not user:
        out(f'No account named {args.username!r}.')
        return 1
    try:
        password = ask(f"New password for {user['username']}: ")
        if ask('Type it again: ') != password:
            out('The two entries did not match. Nothing was changed.')
            return 1
        auth.check_password(password, user['username'])
        store.set_password(user['id'], auth.hash_password(password))
    except (auth.AuthError, TrackerError) as error:
        out(f'{error} Nothing was changed.')
        return 1
    out(f"Password reset for {user['username']}. Their existing sessions were signed out.")
    return 0


def main():
    store = TrackerStore(DB_PATH)
    try:
        return run(sys.argv[1:], store)
    finally:
        store.close()


if __name__ == '__main__':
    raise SystemExit(main())

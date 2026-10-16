"""Root-owned, commit-specific activation evidence. No HTTP or secret output."""
import json
import os
from pathlib import Path
import stat
import subprocess

from corner.collection_policy import parse, TOTAL, PROTECTED
from corner.credit_governor import Refused
from pipelines.collection_provider import EARLIEST

EVIDENCE = ('live_driver_reviewed', 'writer_role_reviewed', 'writer_staging_smoke_test',
            'quota_reconciliation_tested', 'pause_and_recovery_tested',
            'exchange_classification_verified', 'offserver_backup_restore_tested',
            'full_slate_throughput_measured', 'log_secret_redaction_checked')
APPROVAL = Path('/etc/corner/collection-activation.json')
ROOT = Path('/srv/corner/app')
STATE = Path('/srv/corner/config/collection-live.sqlite3')
RETAINED = Path('/srv/corner/collection')


def activation(now, *, startup=False):
    if os.environ.get('CORNER_COLLECTION_ENABLED') != '1':
        raise Refused('Live collection is disabled')
    if now < EARLIEST:
        raise Refused('No activation before October 19 Central')
    if os.environ.get('CORNER_PRIVATE_BETA') != '1':
        raise Refused('Explicit deployed beta mode required')
    expected = {'CORNER_COLLECTION_DB': str(STATE),
                'CORNER_COLLECTION_RETAINED': str(RETAINED),
                'CORNER_COLLECTION_DB_HOST': '127.0.0.1',
                'CORNER_COLLECTION_DB_PORT': '5432',
                'CORNER_COLLECTION_DB_NAME': 'corner_staging',
                'CORNER_COLLECTION_DB_USER': 'corner_collection_writer'}
    if any(os.environ.get(k) != v for k, v in expected.items()):
        raise Refused('Dedicated live paths and writer connection must match deployment')
    if not os.environ.get('ODDS_API_KEY') or not os.environ.get('CORNER_COLLECTION_DB_PASSWORD'):
        raise Refused('Dedicated worker credentials are absent')
    try:
        info = APPROVAL.lstat()
        parent = APPROVAL.parent.stat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or parent.st_uid != 0 or parent.st_mode & 0o022:
            raise Refused('Activation evidence must be root-controlled')
        approval = json.loads(APPROVAL.read_text(encoding='utf-8'))
        if approval.get('approved') is not True:
            raise Refused('Explicit activation approval is absent')
        evidence = approval.get('evidence', {})
        if any(not isinstance(evidence.get(k), str) or not evidence[k].strip() for k in EVIDENCE):
            raise Refused('Activation acceptance evidence is incomplete')
        commit = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True, stderr=subprocess.DEVNULL).strip()
        if approval.get('release_commit') != commit:
            raise Refused('Activation approval does not match deployed release')
        if not isinstance(approval.get('cycle_id'), str) or not approval['cycle_id'].strip() or not parse(approval['cycle_start']) <= now < parse(approval['cycle_end']):
            raise Refused('No explicitly approved current billing period')
        if startup and not 0 <= (now - parse(approval['quota_checked_at'])).total_seconds() < 300:
            raise Refused('Fresh provider quota approval required at worker startup')
        if startup:
            used, remaining = approval['provider_used'], approval['provider_remaining']
            if type(used) is not int or type(remaining) is not int or used < 0 or remaining <= PROTECTED or used + remaining != TOTAL:
                raise Refused('Explicit 15M provider quota approval required')
        return approval
    except (OSError, KeyError, TypeError, ValueError, subprocess.SubprocessError):
        raise Refused('Activation evidence is absent or invalid') from None

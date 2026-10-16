# Coordinated checkpoints — candidate based on a6b4025

This source patch does not enable collection, install a collector unit or change
provider credentials/activation evidence. It introduces one precreated private
lock inode shared by the future live worker, operator administration and the
separately installed root backup tool.

## Protocol

- Path: /srv/corner/config/collection-maintenance.lock, regular file, corneradmin,
  mode 600. Setup explicitly creates it once and preserves any existing inode.
  Code never truncates/replaces/unlinks it. Do not recreate it while participants
  run; advisory locks are attached to the inode, not a pathname.
- Linux flock SH covers startup DB/ledger checks and every entire Runner.tick,
  including discovery, dispatch, accounting, snapshots and PostgreSQL outbox
  publication. The shutdown lease update also takes SH or leaves expiry to safe
  recovery if a checkpoint is holding EX. Checks with collection disabled do not
  create or require a lock file.
- Root backup takes EX for the full checkpoint/encryption operation, with a
  bounded 300-second wait. It cannot enter partway through a running tick. Once
  acquired, new worker ticks return backup_maintenance without dispatch or ledger
  writes. The process stays running; no stop/restart, quota reset or approval
  refresh is performed by backup. Accounts and member readers stay online.
- Mutating collection_admin commands take EX as well. Read-only status does not.
  Existing worker-lease and offline reconciliation checks remain mandatory.
- Context-manager cleanup releases locks after exceptions. OS process death
  releases file locks; it does not refund uncertain provider costs. The ledger's
  existing fencing/unknown-attempt handling still controls recovery.
- Lock acquisition uses read-only descriptors on Linux, so the backup unit's
  ProtectSystem=strict/config-directory restrictions need not be weakened.

The protocol is cooperative. Every process allowed to use the dedicated writer
or mutate the live scheduler must participate; manual ingest/old workers outside
this protocol are prohibited during a coordinated checkpoint. This is not a
database-wide lock against an arbitrary administrator. Backup still checks for
open dedicated writer connections and monitors scheduler data_version across the
PG/SQLite/retained checkpoint, failing on an unexpected concurrent change.

## Deployment order

1. Review/apply/commit/push this SOURCE patch; pull it on the VPS. No frontend
   build or app-service restart is needed. The collector remains disabled.
2. Run the existing 165 regression tests plus tests.test_collection_maintenance.
   Windows local checks intentionally skip three Linux-only cases; ALL lock
   tests must pass without skips on the VPS before enabling coordinated mode.
3. Run the separate prepare-maintenance-lock.py AS corneradmin, not root. It
   creates no live ledger and never overwrites an existing lock inode.
4. Upload the matching backup bundle. Run test_backup.py (18 cases) and
   test_maintenance.py (11 cases on Linux). Install collection_maintenance.py
   beside corner_backup.py/restore_checkpoint.py under the root-owned tool path.
   The source and installed helper copies MUST be byte-identical.
5. After those checks, add coordination_mode="maintenance-lock-v1" to root's
   /etc/corner/backup.json, preserving enabled and the exact recipient. Absence
   of this field retains stopped-only behavior, although the shared lock is
   still required by the updated backup tool.
6. Run one encrypted checkpoint with the existing live collector DISABLED and
   verify status. Rehearse lock contention using synthetic child processes only.
   This does not authorize funded calls. Keep the existing backup timer schedule.
7. Before future live activation, verify the loaded worker actually uses this
   source, long checkpoint/lease expiry recovery, bounded real tick duration,
   actual live-ledger/outbox restore/replay, and the source-pinned activation
   approval. Synthetic locks alone are not funded full-slate acceptance.

## Tests

The multiprocess tests cover a running tick blocking backup, a held checkpoint
preventing a new tick's side effects, exception/process-crash unlock, unchanged
lock inode/content, shutdown while waiting, and a ledger+retained-file checkpoint
that cannot see a partial tick. Linux cases additionally cover simultaneous
shared holders, private file permissions and symlink refusal. Windows uses
exclusive byte locks for disposable tests; this does not prove Linux flock.

Backups may time out if a discovery/tick is too long. This is an explicit failure
with no success archive rather than taking an inconsistent snapshot. Full-slate
timings, disk use, off-server delivery and backup failure notifications remain
separate release gates. No automatic retention deletion is introduced.

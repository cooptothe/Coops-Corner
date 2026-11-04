# Disk retention

Run `bash deploy/deploy-storage-retention.sh` as corneradmin after pulling this release.
No frontend rebuild is required. The initial cleanup temporarily stops the API,
account writer, collection, trends and backup jobs. The first large compaction may
take substantially longer than later passes. The web process stays running.

The root-owned timer checks every 15 minutes, runs cleanup at 45% root usage, and requires less than 50% after cleanup. Paid requests
also stop at 50% disk usage. Protected data exceeding that target is reported;
it is never deleted to meet a percentage. This cannot guarantee a quota for files
written by unrelated system processes.

All accounts, cash movements, logged bets, results, CLV, financial ledger tables,
unknown/inflight reservations, audits, pending publications and completed backups
are preserved. Only the latest pre-start closing capture per reference book/market is retained
for a logged bet (including each parlay leg). Whole matchup histories are discarded.
Logged bet records, stored results and CLV remain unchanged. Unlogged old odds and
superseded captures are removed. Current prices, pending captures, Lab data,
application files and keys remain. A small verified account safety copy and a
ledger verification receipt are saved privately under backups/storage-account-checkpoints.

SQLite compaction builds a separate candidate, verifies every financial/control
table and database integrity, then replaces the original atomically. It requires
space for the retained subset, not a second full copy of the old ledger. If space
runs out, the old ledger stays intact. PostgreSQL retention preserves current
trusted winners and all referenced observations; deletes run in one transaction
with foreign keys enforced. FULL vacuum then returns its freed pages to disk.
The deletion and vacuum SQL was also checked against PostgreSQL 18 in an isolated
database using the app migrations and synthetic logged, expired and upcoming events.
The final VPS disk percentage is verified by the deployment script.

The collector fix also prevents archived October policy records from blocking
November startup. Current-cycle purchase authorization remains strict.

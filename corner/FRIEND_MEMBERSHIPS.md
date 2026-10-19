# Beta and friend memberships — October 19, 2026

Owner-approved offer:
- Ten beta places, each with seven free days from its immutable trial start.
  Optional $50 beta payment continues through November 20, 2026, 11:59 p.m.
  America/Chicago and locks $50/month pregame standard after release. Those
  who do not pay retain the $125/month standard launch offer. No auto-charge.
- Five separate friend/contributor places, complimentary through the same
  November 20 cutoff. Locked after-release rates: $25/month standard OR
  $50/month live when available. This reserves prices; it does not activate
  live betting, paid data collection or a recurring subscription.
- Operator remains separate. No friend accounts/invitations are automatically
  created; the owner names each recipient through server-only administration.

Existing trial timestamps are NOT reset. The duration becomes seven days, so a
started trial still within its first week can regain access after deployment.
New trials stop when fewer than seven full days remain before the fixed beta
end. Existing paid receipts, founders, invitations and account data are retained.
Friend complimentary access ends at the fixed cutoff even if the global trial
enforcement flag is off. Suspension revokes access/session tokens for either
pool. Suspended members hold their place; closure releases only that pool's
place. Reopening must fit that same pool. Both pools count outstanding invites.

The account SQLite schema migration adds a cohort column with default beta to
existing members/invites plus a friend-rate table. Rates are persisted per
friend, backed up with the account database, and never accepted from a browser.
The migration is serialized and idempotent. Signed membership responses expose
only the current account's rates. Friends cannot request the $50 beta purchase
or be promoted by the beta receipt/grant path.

CLI examples (replace recipient/evidence; do not paste invitation codes publicly):

```bash
.venv-api/bin/python -m pipelines.beta_admin --db /srv/corner/config/staging-tracker.sqlite3 --operator wonya invite FRIEND_USERNAME --kind preview --cohort friend --evidence 'Owner approved contributor'
.venv-api/bin/python -m pipelines.beta_admin --db /srv/corner/config/staging-tracker.sqlite3 --operator wonya grant EXISTING_UNENROLLED_USERNAME --kind preview --cohort friend --evidence 'Owner approved contributor'
.venv-api/bin/python -m pipelines.beta_admin --db /srv/corner/config/staging-tracker.sqlite3 --operator wonya move-friend EXISTING_BETA_USERNAME --evidence 'Owner approved contributor'
.venv-api/bin/python -m pipelines.beta_admin --db /srv/corner/config/staging-tracker.sqlite3 status
```

Normal invitations default to the beta pool. Moving an existing unpaid beta
preview to friend explicitly releases its beta place and revokes old sessions.
Paid founders and members with unresolved payment requests cannot use that move.
No public cohort selector or administrative signup field is trusted.

Deployment: take an encrypted checkpoint first. update-staging.sh validates
both access/payment suites and the web build, stops the old backend processes,
installs friend-rate backup verification, migrates the account store, then
starts the new release. A full SQLite backup contains the locked rates; the
updated backup/restore verifier also fingerprints beta_friend_rates and rejects
changed rate evidence. Older pre-friend archives remain verifiable. Collection and billing
activation settings are unchanged. Existing terms/version acceptance and
previous receipts are retained; any future payment activation needs review of
the new terms version. Do not silently relabel old receipt evidence.

Rollback restriction: older app code does not enforce friend cohorts/rates.
Do not deploy pre-cohort code against a live friend-enabled account store.
Rehearse any full rollback with an isolated restored database and a compatible
cohort-aware build. Never overwrite current member/payment records with an old
backup to force a rollback. Existing reboot evidence remains historical to its
recorded commit; do not overwrite its baseline after this source update.

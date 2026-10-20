# Standard pregame scheduled launch

The owner authorized proceeding directly from the successful three-credit real
NHL capture, idempotent publication, restricted-reader feed and encrypted
post-purchase checkpoint to scheduled collection. Additional repeat recovery
drills are deferred. Existing paused-ledger isolated restore already passed.

`standard-pregame-v1` is a root-approved, commit-bound restricted activation
profile. It retains writer, quota, recovery, credential redaction and backup
evidence. It explicitly does not assert fast-book classification or full-slate
throughput measurement. The default full profile still requires all nine gates.
The runner filters fast-book jobs before reserving credits; the provider also
rejects them before transport. History remains unimplemented and disabled.

Only configured active leagues with an upcoming event in the next 24 hours
receive standard main-market jobs. Main prices use the existing 60-second floor;
props use the existing hourly/15-minute/5-minute/60-second bands. Additional
markets retain their final-30-minute window, 50-event/day and 30k-credit/day caps.
All calls remain within 08:00-midnight America/Chicago. Main and props share
durable existing monthly pools; the separate 1.5M reserve is protected. No claim
of full-slate throughput or complete exchange coverage is made at launch.

`pipelines.collection_enable_standard` verifies the retained real smoke and the
owner-confirmed post-smoke encrypted checkpoint, checks the writer/reader, makes
one zero-credit sports request, reconciles actual provider usage without changing
offsets, and resumes accounting. It prepares a private approval for root to
install. It sets the private worker enabled flag and the staging reader authority
path; no provider key enters staging and checkout is unchanged.

Install `deploy/corner-collection.service`, prepare launch, root-install the
approval, restart accounts/API readers, then start the collector. No web rebuild
is needed. This initial supervised service is started, not enabled at boot:
startup still requires fresh matching quota approval, so an unattended reboot or
crash must not silently resume against stale accounting. Restart=no prevents
repeated purchases on a broken startup. Startup is not a declaration of a fully
accepted unattended release. Capture throughput and exceptions from the running
worker before expanding to fast sources.

Immediate stop: `sudo systemctl stop corner-collection.service`.
Durable pause: `python -m pipelines.collection_admin pause --state
/srv/corner/config/collection-live.sqlite3 --evidence "Operator pause"`.
Resume requires fresh reconciliation and renewed root approval; do not reset any
ledger, paid smoke singleton or provider usage. A monthly quota reset also needs
a new explicit cycle binding; the worker fails closed at the current cycle end.

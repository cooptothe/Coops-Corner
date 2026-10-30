# Collection repair

Run `bash deploy/repair-collection.sh` from `/srv/corner/app` as corneradmin.
It diagnoses locally, stops the worker, checks current quota through the free
sport inventory endpoint, reconciles only a bounded single uncertain request,
renews the existing approval and starts the worker. It does not purchase odds.
Normal collection purchases resume under the existing budgets after startup.
The owner confirmed the API key is exclusive to this VPS collector.

The optional two-minute systemd watchdog repairs only an active worker paused
with exactly one uncertain odds or inventory request at least 125 seconds old
and an unchanged approved release. An inventory request can settle at zero only
when the fresh exclusive-key quota total exactly matches all known settled costs. It attempts at most three
repairs per hour. It does not restart an intentionally stopped worker or pull code.
Disable automatic recovery with `sudo systemctl disable --now corner-collection-recovery.timer`.
Logs: `sudo journalctl -u corner-collection-recovery.service -n 30 --no-pager`.

The recurring failures have separate causes:
- Missing charge evidence after a network/response/settlement failure pauses
  accounting to prevent unbounded spending. Exclusive-key quota totals permit
  reconciliation of one old request only when the delta fits its reservation.
- Malformed provider quotes previously blocked the entire PostgreSQL outbox.
  Definitive FeaturedMarketError captures now stay in the outbox, unacknowledged,
  with an entry in publication_failures marked quarantined. Matching captured
  SQLite scopes expire; healthy later captures continue. Charges remain intact.
- Database or configuration failures still block purchases, with exponential
  publication retry delays from five seconds to five minutes. These failures
  cannot safely be fixed by restarting or inventing permissions.

The duplicate-alternate normalization fix excludes every ambiguous copy at that
exact selection identity while retaining other valid lines. Original captures
remain unchanged. No tool clears quarantines or resets ledgers. Inspect retained
isolated captures before any explicit future replay; they are not acknowledged
as successful publications.

Multiple uncertain calls, inflight inventory, quota drift, expired approval,
credential changes, pool/reserve limits, database permissions and corruption
require operator review. The scripts stop rather than bypass these conditions.
November quota rollover still requires explicit approval of the new cycle.
Existing older resume-publication.sh replays all pending captures strictly;
use repair-collection.sh for routine recovery instead.


## Failed worker recovery

The recovery timer also checks services in systemd's failed state. It leaves
intentional inactive stops alone. A failed worker must pass the same approved
Git commit, rate limit (three attempts/hour), exclusive-key fresh quota,
ledger reconciliation and root approval renewal before restarting.
An active healthy worker does not enter recovery. Publication failures remain
visible and cannot be resolved by ignoring an outbox entry.

Fatal worker output now includes phase, error type, SQLSTATE where applicable,
and source file/line/function. It never prints raw exception text, SQL or HTTP
credentials. A known lease loss has failure_code=lease_lost; other validation
errors remain classified without exposing their messages.

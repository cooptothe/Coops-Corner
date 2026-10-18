# Beta release checkpoint â€” October 18, 2026

Release target: October 20. Go/no-go: October 19 at 8 p.m. America/Chicago.
Owner direction: no spending until funds are available. Do not activate paid
collection, payable checkout, purchase infrastructure, or send wallet transfers.

## Evidence completed locally

- Performance release 6dc2f59: exact saved-odds snapshot digest preserved across
  all 21,673 calculated tool rows; cold catalog benchmark approximately 33.5 to
  16.9 seconds on the same saved dataset. Not a VPS latency guarantee.
- Public HTTPS anonymous readiness, October 18: all route/auth-denial checks
  passed; 20 samples, five concurrent reads, p95 263.2 ms. Public login rendered.
  This does not prove the authenticated browser journey.
- Offline account/payment rehearsal: ten seats, 150 concurrent authenticated
  fixture reads, ownership isolation, disabled checkout, XRP/HBAR/XLM synthetic
  receipts, replay-safe founder grants, two-day trial boundary, suspension,
  copied-session revocation, and isolated account restore all passed.
- Isolated HTTP database rehearsal: ten disposable members, 120 authenticated
  GETs over actual loopback HTTP, 68 games, 6,431 eligible saved quotes, 7,766 tool
  rows. Snapshot consistency, anonymous denial, invalid-token denial, suspension
  revocation and no-store responses passed. Latest p95: Middles 1,372 ms for
  1,000 rows; quotes 1,064 ms; other tested routes 467 ms or less, all within
  the 1,500 ms rehearsal budget. Cold build 8.18 s
  reflects a later, smaller eligible dataset, not another like-for-like speedup.

Evidence files live in `retained/release-evidence/` (private, not committed):
`public-readiness-20261018.json`, `offline-acceptance-20261018.json`,
`member-load-local.json`. Harness sources and regression tests are committed.

## Free checks requiring VPS execution

Run the prepared single deployment batch in the existing VPS terminal. It
preserves the known generated Next type file, refuses unrelated checkout edits,
creates an encrypted checkpoint, fast-forwards main, runs release tests/build,
restarts the existing app services, verifies HTTPS/access guards, and runs the
no-spend acceptance script. It does not install/enable the collector or checkout.

`pipelines.member_load` binds an OS-assigned loopback port, uses disposable signed
members and a temporary SQLite store, loads PostgreSQL in read-only transactions,
blocks provider transports during HTTP exercise, then stops and cleans up. It
does not use production session secrets or modify production accounts/DB roles.
This proves isolated API capacity on the host, not the public proxy/browser or
production account database. The existing offline rehearsal covers account
isolation separately.

If no unexpired eligible saved quotes exist on the VPS, the load report is
`incomplete` (exit 2). The script continues other free backup/readiness checks
while explicitly preserving that open gate. It never fetches odds, changes quote
timestamps, enlarges freshness windows, or substitutes fixtures to claim data
load acceptance. Report a failed test or missing configuration; do not override
the guard to make the batch pass.

## Owner/device checks

Owner confirmed October 18: iPhone/Safari sign-in, EV, Props, Lab, Tracker,
Account, filter interaction, parlay open/close, and no clipping/sideways scrolling
all passed on the then-current public deployment. This is owner-reported device
evidence, not automated browser evidence. Add to Home Screen was not confirmed.
Repeat a brief spot check after the new VPS deployment.

- iPhone Safari: sign in; EV, Props, Lab, Tracker, Account; filters; parlay open/
  close; book links; portrait layout and no sideways scrolling. No paid refresh
  or payment needed. Test Add to Home Screen and launch from its icon.
- Confirm authenticated public member journey after VPS update. Keep passwords,
  session cookies and recovery keys out of chat and evidence output.
- Confirm VPS reboot/rollback in a controlled maintenance window. Automated
  build fallback is not evidence of a full release/database rollback or reboot.
  Do not restore old account/payment data over current records.
- Existing encrypted off-server manual restore proof remains evidence;
  unattended off-server backup destination remains deferred by owner choice.

## Deferred until funded and explicitly reviewed

- Bounded provider smoke, actual purchased quota/cycle reconciliation, approved
  main/props cadence and full-slate credit forecast. Current code requires explicit
  15M quota evidence; it must not be bypassed with the small local allowance.
- Initialize the live ledger paused; include ledger/outbox/captures in a fresh
  coordinated checkpoint and prove recovery before collector activation.
- Real receive verification for XRP/HBAR/XLM and operator review/grant workflow.
  Synthetic receipt tests do not prove real wallet delivery. No ONDO.
- Root-controlled activation evidence must match the final deployed commit.
  New code invalidates any older commit-specific approval.
- Independent predictive calibration/source coverage remains separate from
  arithmetic and UI tests; do not represent estimated probabilities as proven
  win rates or guarantee profitable outcomes.

No paid launch sign-off is recorded by this checkpoint. Freeze features and close
the production, device, data/quota and payment evidence gaps before go/no-go.

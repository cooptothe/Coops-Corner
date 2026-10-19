# No-spend beta acceptance — October 18, 2026

## Boundary

No new purchase, funded transfer, payable production invoice, paid odds request, collector activation, or server reboot is authorized by these checks. Synthetic flags and receipt evidence exist only in a temporary account database. Receiving-wallet balances do not matter for this phase. Real receive/chain verification and live provider/quota evidence remain deferred until the owner funds and authorizes them.

## Available checks

- `python -m pipelines.beta_rehearsal --output retained/release-evidence/offline-acceptance.json`: disposable ten-member fixture exercise with external HTTP transports blocked. Concurrent sign-ins and 150 authenticated reads cover personal ledger isolation, no-store, seat cap, disabled checkout, three synthetic payment/approval flows, seven-day trial timing, founder pricing, session revocation, SQLite recovery and exactly-once receipt replay. It never opens a real server port or touches production accounts. Measured latency is an in-process fixture benchmark, not a VPS load result.
- `python -m pipelines.release_probe --base-url https://coopscorner.tech --output retained/release-evidence/public-readiness.json`: bounded anonymous GET requests to public pages, the install manifest/icons, protected API routes and a retired route. TLS verification stays enabled and redirects are not followed. Checks cannot call refresh POST, create a payment, submit credentials or reach the odds provider. Anonymous latency does not establish authenticated or database performance. The initial anonymous HTTP p95 review budget is 1.5 seconds; exceeding it is a failure requiring review, not a false pass.
- `bash deploy/verify-beta-no-spend.sh` on the deployed VPS: asserts provider keys absent and collector/checkout disabled before running the disposable acceptance, public checks, actual encrypted checkpoint, and supervised read-only HTTPS monitor. Configuration values and secrets are never printed. It installs a five-minute readiness timer only after its first check passes. The monitor makes bounded GET requests and reports failures in systemd journal; it does not provide external outage notifications, database readiness, or odds-freshness monitoring.

## Installation basics

The App Router manifest, branded 192/512px icons and Apple home-screen icon support adding the site to a phone's home screen. Account explains Safari/Chrome steps. No service-worker or offline odds cache is registered. The installed app still requires sign-in and a network connection. Device-specific install affordances must be verified on real iOS/Android browsers.

## Release evidence and remaining gates

Save output under retained/release-evidence (private local runtime files, not committed member data). Latest source commit and test success are required but do not prove VPS deployment. Backups have previously passed isolated PostgreSQL restore; the new command additionally rehearses post-payment SQLite recovery without real funds. Fresh encrypted server backup succeeds only when its actual systemd service reports success.

Still required before paid launch: observed VPS deployment and reports, actual device member journey, authenticated VPS concurrency, reboot plus compatible rollback, real receiving verification for each offered asset, current live quota reconciliation/provider smoke and explicit activation. Earlier successful fixtures must not be presented as proof of these remaining production gates.

The release plan targets October 19, 6 p.m. Central freeze / 8 p.m. decision, and October 20 staged rollout. Today is for acceptance and blockers. No new feature expansion is needed to run this stage.

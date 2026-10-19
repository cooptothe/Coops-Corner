# Free recovery checks — October 19, 2026

Previous VPS deployment was confirmed at 0ef5904: production build, 197 frontend
checks, 108 no-spend acceptance tests, public HTTPS/access guards, encrypted
checkpoint and active backup/readiness timers passed. Collector/checkout were
disabled and provider keys absent. VPS saved-odds load was correctly incomplete
with zero eligible quotes; empty-response latency is not realistic feed proof.

Owner confirmed Bluehost console access and approved a brief beta interruption.
Run `bash deploy/verify-recovery-no-spend.sh` in the existing VPS terminal.
The first run checks the installed units, disabled collection/checkout,
configuration continuity prerequisites, and an encrypted checkpoint, then
performs the approved reboot. It never enables or installs a collector.
After SSH returns, rerun the SAME script. Do not pull another commit between
these two runs: acceptance requires the same release and private configuration.

Before reboot it starts an isolated copy of the current production web build on
an OS-assigned loopback port. It copies .next without the disposable cache, plus
public assets/config, and uses installed dependencies. Login, Lab, manifest/icon,
and anonymous API denial must pass. The isolated server is stopped and the copy
removed; live web files are not replaced. This verifies web-artifact recovery,
NOT rollback to a different backend/schema release or loss-free payment recovery.
The private startup log is retained for diagnostics without printing credentials.

The boot check refuses active or enabled collector units and any collector in
the multi-user boot dependency graph. Required app, proxy, database and monitoring
units must be enabled and active. PostgreSQL and internal application ports must
be available only on loopback. Private staging/worker/billing/session material
fingerprints are saved to a mode-600 baseline, never printed. After reboot the
kernel boot ID must differ while release/configuration fingerprints must match.
No secret contents, provider requests, wallet transfers, account mutations,
configuration changes, database restores or historical re-dating occur.

Evidence files in retained/release-evidence:
- web-artifact-recovery.json / web-artifact-recovery-server.log
- reboot-before.json (private baseline; do not overwrite it to force a pass)
- reboot-after.json / public-after-reboot.json

A failed prerequisite stops before reboot. A failed post-boot check is not a
pass; keep collection/checkout disabled and use the approved browser console
if SSH fails. The script never repairs service settings or private configs
silently. An existing baseline with the same boot ID means reboot is still
pending; a changed boot ID runs verification without rebooting again.

Still open: real-data VPS load (no eligible saved quotes on last run), funded
provider/quota and XRP/HBAR/XLM receive checks, full prior-release application/
database rollback, and Add to Home Screen installation. Ordinary iPhone Safari
navigation/filter/parlay checks were confirmed by the owner on October 18.

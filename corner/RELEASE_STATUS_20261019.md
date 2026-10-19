# Beta release gates — October 19, 2026 (America/Chicago)

Target remains October 20. The previous plan scheduled the October 19 decision at
8 p.m. Central; a target date does not override activation gates. No paid launch
sign-off is recorded. Freeze new features and close evidence gaps.

## Confirmed history

- Owner confirmed iPhone Safari navigation, filters, parlay drawer, and no clipped
  controls; subsequently confirmed Add to Home Screen installation and launch.
- The earlier controlled reboot and isolated saved-web-build recovery exercise
  were completed in this conversation. Keep their original evidence and release
  identity. They do not establish current-release or prior-backend/schema rollback.
- Public HTTPS, anonymous access denials, loopback-only internal listeners,
  encrypted checkpoints and isolated restores were previously checked.
- Owner supplied VPS deployment output through f05dd94, including the new beta
  invitation links. Existing test membership was to be closed and replaced by
  the tenth code; do not infer that command succeeded without its output.
- Friend and beta membership/pricing are separate. Seven-day beta trial; optional
  $50 beta fee and $50/month standard founder rate; unpaid launch standard $125.
  Five friends receive complimentary beta through November 20 and locked $25
  standard / $50 live-when-available monthly rates. No automatic charge starts.

## Open free gates

1. Owner answered "Not yet" for a real invitation signup on the public site.
   An intended member should open their private link, read/accept terms, choose
   their own username, confirm code prefill, and verify correct Account access.
   Do not consume an extra seat with another disposable production test account.
2. After that signup, run the public member API check using that member's login:

       .venv-api/bin/python -m pipelines.public_member_probe

   Enter credentials only in the terminal prompts, never command arguments/chat.
   The destination is fixed to verified HTTPS at coopscorner.tech. It makes one
   login attempt, fixed read-only requests, and logs out its own probe session.
   It does not refresh odds, create accounts, mutate bets/preferences, request
   invoices, initiate payments or enable services. Login failures may count
   toward ordinary account rate limits. Use a member, not an operator.
   Credentials/cookies/private bodies are omitted from the private report.
   This is one-member API/proxy evidence, not browser, concurrent-load or
   predictive-accuracy proof. Empty feeds cannot establish realistic data load.
3. Current VPS saved-odds load remains INCOMPLETE because no eligible quotes
   exist. Do not change timestamps/freshness windows or fetch paid data to hide
   this. Earlier local fixture/historical volume results have separate scope.
4. Full prior-release backend/database compatibility rollback remains unverified.
   Do not roll current production accounts back to a pre-cohort or pre-open-beta
   code/schema: that can break invitations and pricing. Isolated web artifact
   recovery and restored-copy database verification are narrower completed checks.
   Plan a compatible release plus isolated checkpoint rehearsal before sign-off.

## Deferred paid activation gates

- Explicit provider plan/quota/cycle reconciliation and bounded live smoke.
- Initialize live ledger paused, include outbox/captures in a coordinated backup,
  prove restored pending-publication recovery for the actual activation state.
- Real receive checks for every enabled XRP/HBAR/XLM asset, then supervised manual
  verification. Synthetic receipts and correct wallet addresses are insufficient.
- Activation evidence must match the final deployed release. Keep collection and
  payable checkout disabled until their individual checks pass and are authorized.
- Automated remote backup storage remains intentionally deferred; local encrypted
  automation and manually downloaded recovery are not unattended off-server copies.

## Decision

A private preview can be reviewed while collection and checkout stay disabled.
Fresh paid feeds and payments are NOT ready just because tests/builds or the
invitation page pass. Do not tell members their feeds are live until verified.

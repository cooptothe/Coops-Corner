# Two permanent brother memberships

Owner authorized two additional family places, separate from ten beta and five
friend places. Each is a normal member account, not an operator. Standard and
live tools are complimentary permanently, when available. No trial, beta-end
cutoff, subscription or payment is required. Suspension/closure remains an
operator control; it revokes sessions. Accounts and codes are personal.

New family invitations allow the recipient to choose a username. Each code
expires seven days after issuance, can be used once and requires the existing
welcome agreement. The resulting access does not expire. Reading the welcome
page does not claim the code. Do not publish or commit the private links.

Only the server operator CLI issues these grants. Client-submitted cohort,
pricing, role or access fields cannot create a family entitlement. Two family
places are reserved atomically and count separately, including outstanding
invitations and suspended members. Re-running issuance returns the same two
links from /srv/corner/config/brother-invitations.json (mode 600). If that
receipt is lost, automatic issuance refuses to create extra places. It does
not recover plaintext tokens from their stored hashes or revoke working links.

The migration adds beta_family_invites and beta_family_members markers. To
avoid rebuilding the existing cohort CHECK constraints and linked billing
tables, underlying rows use the legacy friend storage value; effective family
cohort is resolved exclusively from the operator-created marker. Friend counts,
rates and expiry exclude these marked rows. API responses, access guards,
welcome terms and billing use the effective family cohort. Beta mode can be
disabled after release without losing or charging permanent family access.

SQLite snapshots preserve these tables. Updated billing checkpoint metadata
hashes both tables so recovered grants and reservations can be checked. Raw
links are retained privately for issuance convenience; access recovery depends
on the account database, not the plaintext link receipt. No wallet/provider
request or payment activation is needed to issue invitations.

Deploy with deploy/update-family-invitations.sh after stopping the collector
and pulling the release. It uses existing recovery/approval controls and prints
the two private links last. Existing pools, prices, quotas and fetch intervals
remain unchanged. Website service restart is required for the new access rules.

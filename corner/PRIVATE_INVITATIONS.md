# Private family invitations

Both pools use `/invite#CODE`. The fragment keeps the code out of normal page requests. Treat the entire link as a secret: anyone holding an unclaimed friend link can claim it. Codes are transmitted only in bounded same-origin POST bodies. Do not enable request-body logging for these endpoints. No third-party images, fonts, analytics or scripts are added.

## Existing codes

Do not issue another five codes if five places are already reserved. Run the following once per existing code, entering it at the hidden prompt:

    .venv-api/bin/python -m pipelines.invitation_admin --db /srv/corner/config/staging-tracker.sqlite3 --operator wonya link

This validates the existing invitation, marks agreement required, and prints its branded link after commit. It does not reserve another place, extend expiry or recover a lost raw code. For lost/expired codes use the existing revoke/reissue workflow explicitly.

Beta invitations work with the same command. Their existing intended username still applies. Friends keep their separate five-place pool; the ten beta places are unchanged. Paid-beta invitations show already-verified access rather than asking for payment again.

## Feedback

    .venv-api/bin/python -m pipelines.invitation_admin --db /srv/corner/config/staging-tracker.sqlite3 --operator wonya feedback

Review output privately. This lists the latest 100 reports; it sends no emails. Reports are plain text, limited to five per invitation per hour. Unclaimed links may submit while valid; claimed links require the matching signed-in account. Agreement versions, the accepted offer, invitation markers and feedback are covered by the account backup and billing checkpoint tables. Existing plain-code invitations remain compatible until explicitly wrapped.

No invitation operation enables trials, collection, payments, live packages or recurring billing. No main-app help navigation was added. Confirm actual access in Account. The invitation explains current separate trial activation honestly.

## Prepare all five friend links

    bash deploy/prepare-family-invitations.sh

If five friend places have never been reserved and the pool is empty, this creates five one-time codes and prints the five links after commit. If live invitations already exist, it asks privately for their saved raw codes and wraps them without new reservations. It cannot recover hashes into lost codes. Already-enrolled friends retain their seats. It does not create additional reservations to fill an already-used pool. A checkpoint follows successful preparation.

New `beta_admin invite` and `friend-codes` output branded links automatically and require the welcome agreement. Existing named beta codes can be wrapped with the single-code command above once their recipients are ready. Share links yourself; this update sends no invitations or emails.

## Username-free beta links

    .venv-api/bin/python -m pipelines.invitation_admin --db /srv/corner/config/staging-tracker.sqlite3 --operator wonya betas

With no unused beta invitations, this issues links for the remaining available beta places (ten minus active/suspended members and reservations). If unused codes already exist, it asks for those codes and prints their links without adding reservations. It never removes current members or changes paid/friend pricing. New beta codes let recipients choose usernames at signup. Legacy specifically named invitations remain identity-bound; revoke and replace them explicitly if that restriction is unwanted.

For a smaller batch use `beta_admin ... beta-codes --count N --evidence "Owner-approved beta trial"`. The ordinary `invite` command now accepts an omitted username too. Paid-beta evidence is still an explicit operator-only action; the bulk command issues trials only.

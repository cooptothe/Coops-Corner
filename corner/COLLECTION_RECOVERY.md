# Collection recovery and isolated failures

Verified HTTP/quota responses with invalid snapshot data or rejected scope
(400/404/422) now settle the confirmed charge and quarantine the job. The scope
is excluded from ready/claim checks, so it is never repeatedly purchased. Its
prior live snapshots expire immediately. Other scopes continue. Small invalid
payloads remain in the private ledger for diagnosis; no malformed odds publish.
Quota drift, excess charges, account failures, throttling, missing quota evidence
and uncertain transport failures still stop purchases. There is no blanket
automatic restart, duplicate paid retry, accounting reset or speculative refund.

Runtime failures now record phase, exception class, request token and job scope
without exception messages, URLs, passwords or API keys. Quota audits preserve
verified actual cost and HTTP status so a local snapshot failure does not erase
already received charge evidence. Quarantine remains enforced across resume and
process restart. The administrator must review the saved scope and correct its
cause before explicitly releasing it; normal resume does not remove quarantine.

`python -m pipelines.collection_recover` requires a stopped worker, the existing
bound key, root-controlled standard approval and fresh zero-cost provider quota.
It can recover one unknown request when its saved verified response and total
accounting prove the cost. All settled charges, offsets and metadata costs remain.
It resumes healthy scopes and prepares renewed commit/quota approval for root
installation; it does not start the service or purchase odds.

The explicit `--accept-single-request-quota-delta` flag is an operator accounting
decision, not an automatic retry policy. It requires the operator to suspend all
other consumers of this provider key. With exactly one old unknown request, no
inflight requests or unknown metadata, it assigns fresh provider total minus all
known costs to that request, only within the original reservation. It records
that attribution as operator-accepted total-delta evidence, including a verified
zero difference where applicable, rather than pretending to possess a missing
response. Requests younger than 120 seconds and out-of-cycle uncertainties are
refused. Unexplained excess usage is never silently allocated elsewhere. Any
subsequent provider drift pauses collection again.

This initial rollout does not provide external notifications or automatic
reconciliation of truly unknown charges. The service journal and collection_admin
status expose the state; an active systemd process alone does not prove collection.
After restart, verify fresh main scopes, new publication acknowledgements and
increasing settled requests, with no new unknown requests. Reopening a member
page does not restart a paused worker or force provider fetching.

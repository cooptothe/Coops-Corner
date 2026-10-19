# Member checkout with manual verification

## Deployment remains disabled

No CORNER_BILLING_CONFIG is installed or set by this patch. Missing, unreadable, malformed, disabled or incomplete configuration closes checkout. Local mode also closes it. No odds provider or blockchain requests, wallet keys, transfers or automatic subscriptions are introduced. There is no public approval endpoint.

A later reviewed configuration must have payments_enabled=true, memo_reviewed=true, receive_test_passed=true, manual_review_ready=true, the current beta_terms.VERSION, support_email and exactly the three validated native receivers. The existing disabled receiver fixture is not approved for live use. Confirm memo/tag requirements and supervised funded receive results before enabling anything.

## Customer flow

Account shows the confirmed seven-day trial, one-time $50 beta option, fixed November 20 end, no refunds, fee responsibility, $50/month founder pregame standard-market package after launch, and $125/month standard offer for those who skip beta payment. A member explicitly accepts the current terms and chooses a coin before requesting a quote. Existing active preview members consume their existing seat; operators and paid members cannot create a purchase request.

A request waits for the operator to supply a reviewed current USD rate. Quotes last no more than ten minutes from rate observation; stale or future observations are rejected. Customer Account polls only its own payment request every 30 seconds while visible. It shows the exact native amount, network, reviewed receiving address, required memo/tag and copy controls. The quote disappears at expiry. A submitted transaction reference goes to review; it cannot unlock membership. Never send a second payment merely because a receipt needs review. Rehearsal quotes remain nonpayable even after checkout is subsequently enabled.

## Operator workflow after separate activation review

Use the server-only pipelines.billing_admin with --db, --operator and --env-file pointing to staging.env when quoting. The private environment must point CORNER_BILLING_CONFIG at the reviewed JSON. `pending` lists member requests and states; `inspect REQUEST_ID` shows the bound quote and claim. `quote REQUEST_ID --rate PRIVATE_JSON` takes exactly usd_per_coin (decimal string), observed_at (Unix seconds within the last minute), and source (independent rate reference). Obtain a current rate yourself; this tool never fetches or fabricates it.

`approve REQUEST_ID --review PRIVATE_JSON` uses the exact fields documented in MANUAL_BETA_PAYMENTS.md. Verify received funds in Exodus and a native explorer, including actual delivered amount, native network, destination, memo/tag, final success, timestamp, operation/transfer index and the paying member's attribution. Public transaction references alone do not prove who paid; resolve ambiguous ownership privately rather than granting either claimant automatically. Underpayment, overpayment and late transfers are exceptions for private review. No automatic refund, second charge or silent repricing occurs.

Approval commits the invoice, unique receipt, paid access and founder flag together. Replays and recovered replays cannot add receipts or duplicate grants. Approval revokes the previous session; the member signs in again and sees the founder rate. No recurring billing is activated.

## Recovery and remaining activation gates

Invoices, terms acceptance, quote evidence, claims and receipts are stored in the existing account SQLite file, covered by its full database checkpoint. A restored approved invoice replay was tested without duplicates. The new external billing JSON must also be added to the backup file list and recovery verification before live activation; restore must keep checkout disabled until reviewed. Customer controls remain hidden until the separate reviewed configuration is installed. This release does not enable trial clocks, paid checkout or collection.

Owner confirmed on October 17 that XRP, HBAR and XLM receive no memo/tag in Exodus. The disabled receiving fixture now records memo_reviewed=true and null memos, while receive_test_passed, manual_review_ready and payments_enabled remain false. This is not evidence of funded receipt.

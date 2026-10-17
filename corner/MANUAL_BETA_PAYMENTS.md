# Manual crypto payment workflow: offline preparation

The operator chose manual verification. No automatic chain verifier, wallet connection, private key, funds transfer or recurring charge is required by this workflow.

## Completed in this stage

BetaInvoices stores one open payment request per active preview member, exact versioned terms acceptance, supported asset, an operator-supplied timestamped rate and its source, a ten-minute quote, transaction claim and audit trail. It uses exact native base units. Requests reuse the existing member seat. Quotes are explicitly rehearsal-only and public status omits receiving instructions. No production route creates a payable invoice yet; payment POST routes return payments_disabled after authentication/origin checks.

A submitted reference never grants access. Only explicit operator approval records reviewed receipt evidence, fulfills the existing paid ledger and grants paid_beta plus founder pricing. These changes and invoice status commit in one transaction. A crash rolls back all changes; an identical replay creates no second receipt, grant or session epoch change. Wrong amount, destination, memo or receipt time requires private resolution. Never instruct someone to pay again merely because a transaction needs review. Late claims are retained, not auto-approved. Submitted claims cannot be cancelled or replaced by the member.

Founder price: $50/month for the pregame standard-market package after launch. Members who skip the beta payment can subscribe at the standard $125/month. The initial $50 is one-time beta access through November 20. No automatic conversion, renewal or recurring charge. Terms version is advanced to include the founder offer.

## Manual review procedure before future activation

Inspect the request with the server-only billing_admin inspect command. Independently compare Exodus and a native-network explorer: exact native asset/network, destination and required memo/tag, actual received amount, successful final settlement, timestamp and transfer/operation index. Do not accept a screenshot or submitted hash as proof. For XRP use actual delivered_amount, not the requested Amount. Record a private review JSON with exactly: evidence (wallet/explorer review reference, 10-300 characters), delivered_base_units (integer string), destination, memo (string or null), received_at (Unix seconds), transfer_index (integer).

The server-only billing_admin approve command accepts that JSON and the request ID. It requires the bootstrapped active operator. Underpayments, overpayments and late arrivals are review exceptions; no automatic refund or second-payment instruction is provided. Paid upgrades revoke existing sessions, so the member signs in again to see the founder status.

## Still required before asking members to send

Confirm wallet memo/tag requirements and funded receive tests. Connect customer request/quote/claim UI and reviewed receiving configuration; obtain a real rate with explicit source/time and rehearse member-to-operator approval. Back up the account database and recover it in isolation before activation. No payments or live collection were enabled by this patch. The invoice, quote, claim and receipt records live in the account SQLite database and are covered by the full-database backup.

References checked October 17, 2026:
- https://xrpl.org/docs/concepts/transactions/finality-of-results/look-up-transaction-results
- https://xrpl.org/docs/references/protocol/transactions/types/payment
- https://developers.stellar.org/docs/learn/fundamentals/transactions/operations-and-transactions

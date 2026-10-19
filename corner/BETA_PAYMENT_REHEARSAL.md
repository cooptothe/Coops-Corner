# Beta payment workflow preparation — not activated

The owner confirmed ten members, **two free days per member**, followed by an
optional **one-time $50 USD** crypto payment for beta access through **November 20,
2026**. November 20 is included: access ends November 21 at midnight Central,
06:00 UTC. No automatic charges or renewal. The stated policy is **no refunds**.
Accepted coins are **XRP, HBAR and XLM** on their native networks, received in the
operator's Exodus wallet. **ONDO is removed.** No customer wallet connection or
secret phrase is needed. The owner supplied public XRP/XLM addresses and an HBAR account, plus
admin@coopscorner.tech for support. XRP/XLM checksums and the HBAR numeric format
passed offline validation. Ownership and successful receiving remain unverified.
The disabled receiving configuration stores these public details; it contains no
wallet key or seed. Exodus documentation says its receiving wallets do not require
a memo/tag; memo review remains part of the supervised receive test.

`beta_terms.py` defines the offer, seven-day timing, fixed beta end and exact native
amount calculations. It does not yet alter running account authorization.
New trial enrollment should close during the final 48 hours so every advertised
trial can receive two full days. Existing preview accounts are not silently
converted or cut off by installing this offline foundation.

The offline receipt ledger is a first-stage foundation, not a checkout or
blockchain verifier. It is not invoked by an application route or startup script.
A separate authenticated, read-only billing-status route previews the confirmed
offer on the Account page. It exposes no receiving addresses or send-funds control.
No payment should be requested using this preparation alone.

## Verified with synthetic records

- Recording a reviewed receipt does not grant access.
- An active operator is required for all mutations.
- The same canonical network/transaction/transfer index cannot pay two members.
- Conflicting evidence on a recorded transfer is rejected; exact replay reuses it.
- Positive integer base units preserve the exact quoted crypto amount; floats
  cannot silently round a payment into acceptance.
- A fulfilled receipt atomically creates one paid invitation or upgrades an active
  preview member. A repeat creates no second seat or invitation secret.
- Full capacity or an injected crash rolls back access changes and leaves the
  receipt available for operator resolution. Preview upgrades revoke old sessions.
- Receipt records live in the same account SQLite database covered by the existing
  whole-database backup, without a second mutable copy of membership status.

## Required before a real payment workflow

1. Use the confirmed offer and support contact above.
2. Approve versioned customer terms; record the member's acceptance before payment.
3. Configure independently checked public receiving instructions for each exact
   network and asset/contract, including any required memo/tag. No private keys.
4. Establish the USD quote source, expiry, fee payer, under/overpayment handling,
   and late-payment review. Do not reuse expired quotes silently.
5. Implement invoice and seat-reservation lifecycle before asking a member to pay.
6. Independently verify settled transfers: exact network/asset, recipient and tag,
   amount, transfer index, status/finality, quote and member binding. A transaction
   screenshot, submitted hash or `settled: true` input is not independent proof.
   The current library accepts an operator attestation; it never checks a chain.
   Real chain adapters must enforce canonical network and transaction identifiers.
7. Wire server-side trial and paid-access expiry, cancelled/failed invoices and
   incorrect-payment review. The pure timing policy is tested; application access
   enforcement and invoice lifecycle are not connected in this foundation.
8. Rehearse backup/restore of the extended account database and operator receipt
   recovery. Then complete funded receive verification at the agreed date. The
   owner chose no membership refunds; no refund button or automatic transfer is added.

No public unauthenticated endpoint, automatic payment polling, wallet connection,
transfer, renewal or customer invoice was added. The account offer card says that
payments are not open and current preview access is unchanged. Existing preview
access and collection settings remain unchanged. A paid launch remains gated.

Offline command after applying the preparation patch:

`python -m unittest tests.test_beta_receiving tests.test_beta_terms tests.test_beta_billing tests.test_billing_offer tests.test_beta_access tests.test_accounts`

## Customer flow to implement

Invitation → account → seven-day trial → optional **Continue beta — $50** → choose
XRP/HBAR/XLM → receive a time-limited exact amount and Exodus receiving address
with Copy/QR controls → submit transaction reference → payment review → access
through November 20. Show price, end date, no refunds and network fees before the
member sends anything. An expired trial should retain account and payment access
while member feeds are locked. A screenshot or client claim cannot unlock access.

Payment instructions stay unavailable until receiving details pass a supervised
receive test and terms acceptance, invoices and independent receipt verification
are connected. The trial clock is not yet enforced in running account guards.

## Reference documentation checked October 17

- Exodus receiving and network matching:
  https://www.exodus.com/support/en/articles/8616180-how-do-i-receive-bitcoin-and-crypto-in-exodus
- Exodus memo/tag handling:
  https://www.exodus.com/support/en/articles/8598641-what-is-a-memo-or-destination-tag-and-how-do-i-use-them
- Exodus transaction inspection:
  https://www.exodus.com/support/en/articles/8598818-how-do-i-find-transaction-information-on-a-block-explorer

# Local accounts and retrospective records

Implemented: local username/password registration, sign-in, logout, eight-hour
database sessions, private completed-bet records, cash bookkeeping, exact USD totals.
No sportsbook credentials, wager submission, actual money movement, automatic
grading, recommendations, or opening new positions.

This is a development slice, **not production account readiness or feature parity**.
HTTPS deployment, recovery, MFA, account deletion/export, corrections, per-book
balances and open-position reporting remain work.

## Start

Build the Spring jar with Java 25 and `mvn -f server/pom.xml package`. From repo root:

```powershell
.\.venv-api\Scripts\python.exe -m server.run_local --initialize-accounts --accounts
```

The explicit initialize switch applies migration 014 only when its schema is absent.
It adds `corner_app`, leaving domain ledgers unchanged. Later runs need only
`--accounts`. Without that switch, account endpoints are disabled. Next.js proxies
`/api/account/v1` to loopback Spring. Open http://127.0.0.1:3000/tracker and create
a local account yourself. Do not reuse a sportsbook password.

Two separate generated temporary logins are used: the market login has SELECT-only
domain access; the personal login has no domain schema access, SELECT/INSERT on
personal tables, UPDATE on auth throttles and the user ID column (for locking),
and DELETE on sessions only. It cannot edit/delete recorded cash or settled bets.
Normal launcher shutdown removes its logins, preserving records. Forced launcher
termination can leave logins needing guarded cleanup.

Local HTTP cookies intentionally omit Secure for loopback development. Do not
expose this service publicly. Production requires HTTPS, Secure cookies and a
separately reviewed deployment configuration.

## Security and accounting

- BCrypt cost 12 with random salts; passwords are never returned.
- 32-byte random session tokens; only SHA-256 hashes stored in PostgreSQL.
- HttpOnly, SameSite=Strict cookie with restricted API path and eight-hour expiry.
- Exact local Origin and custom header required on all writes, including login.
- Authenticated writes also require the session CSRF token.
- 20 authentication attempts per 15-minute username and remote-address bucket.
  Local proxy users can share a bucket; this is not distributed production throttling.
- Ownership comes only from the verified session, never a supplied user ID.
- User-row locks serialize writes and summary reads. Per-user request UUIDs prevent
  duplicate saves; reuse with different input returns 409.
- SQL/Java decimals preserve USD cents. UI inputs and displays American odds.
- Only manually recorded past placements and settlements are accepted.
- Returned amount includes returned stake. P/L = returned minus stake.
- Recorded balance = deposits minus withdrawals plus settled P/L. Open wagers and
  unrecorded activity are excluded; this is not a verified sportsbook balance.

API paths: register, login, session, logout, records, cash under `/api/account/v1`.
Records GET returns totals plus two separate lists of up to 50 entries at a shared
offset. Service failures are errors, not zero balances.

## CLV and remaining scope

CLV is not implemented by this slice. A one-time snapshot cannot establish closing
prices. Follow-up requires exact contract binding, a named benchmark book, a
closing cutoff/window, freshness/coverage checks, immutable source provenance,
and an explicit versioned metric. Latest prices are never silently labeled closing.
Existing betting tools still use their fixture integrations.

## Verification

`python -m acceptance.personal_records` runs 10 disposable HTTP/PostgreSQL tests:
hashes/login, origin/CSRF, decimals/idempotency, tenant isolation, validation,
cash totals, concurrent retries, logout, expiry, and throttling. No provider calls.

References: [Spring password storage](https://docs.spring.io/spring-security/reference/7.0/features/authentication/password-storage.html),
[OWASP session guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).

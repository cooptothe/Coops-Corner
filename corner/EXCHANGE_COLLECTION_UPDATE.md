# Exchange collection update — October 24, 2026

Main lines, additional markets and live still request all six exchange keys: novig, betfair_ex_uk, prophetx, kalshi, betopenly, polymarket_us. Props request all except Betfair. Standard sportsbook groups remain unchanged. Main-line and live Betfair references remain unchanged. Retained Betfair props cannot re-enter normalization, EV references, reference quorum, prop tools or the props sportsbook menu.

The supplied screenshot is a bookmaker identifier, not a credential. polymarket_us was already in the actual transport group. No direct Polymarket credential or new connector is needed. Requests include provider links, native IDs and bet limits when available. Configuration is not proof of current returned coverage; the provider may return no book, market or matching line. No opportunity is manufactured merely to make a book appear.

Fee handling remains unchanged, per the owner's instruction to focus on acquisition.

## Credits

Owner dashboard: 459,541 used; 14,540,459 remaining; 13,040,459 usable above the protected 1.5M reserve. Quota resets November 1 UTC; the November 20 invoice date is separate.

Removing Betfair changes props from 16 to 15 requested books: standard 10 plus exchange 5. Each group still bills as one region-equivalent block. Guaranteed savings are zero. Fewer returned unique markets can reduce actual charges, but that requires evidence; don't allocate invented savings. Core/alternate props remain in the same request and cadence.

Full-November saved-schedule props scenario stays 4,914,836 credits. The shared main/additional/live pool is 7,900,000 including the 500,000 live subcap. Metadata 500,000; Lab history 100,000. Planning envelope 13,414,836; remaining 1,585,164. This is a planning envelope, not a prediction of current October closing usage. Independent main, alternate and live ceilings cannot all be added on top of the shared pool. The shared governor can throttle alternates when other main-pool work consumes the allocation. Hard maximum across all pools remains 13.5M, protecting 1.5M.

No interval or pool increases were made. Main: >12h 15m; 6–12h 10m; 2–6h 5m; 1–2h 3m; final hour 2m. Props, including alternate props: >12h 10m; 6–12h 5m; 4–6h 3m; 2–4h 2m; final 2h 1m. Additional markets: final 2h only, 1–2h 10m; 30–60m 5m; 15–30m 2m; final 15m 1m. Live main lines: 1m. Acquisition window remains 08:00–24:00 America/Chicago. No NCAA player props.

## Read-only operational check

`python -m pipelines.collection_book_coverage --state /srv/corner/config/collection-live.sqlite3` reads a consistent SQLite snapshot in mode=ro/query_only. It prints requested keys, returned/fresh scope counts, missing-data states, collection pause/pending counts, latest known provider usage, unresolved requests and a rolling 24-hour burn-rate scenario. It never imports provider credentials, fetches odds, starts collection or writes the ledger. A retained quote does not prove current availability or positive EV. Live freshness is 90s; pregame remains 30 minutes. After-hours empty freshness is expected.

The 24-hour scenario is withheld when there are unresolved charges or no recent settled spend. It can still understate future busy slates or follow an outage; use it alongside the hard envelope, not as automatic permission to spend.

Primary provider docs checked October 24:
- https://the-odds-api.com/sports-odds-data/bookmaker-apis.html (US exchange keys)
- https://the-odds-api.com/liveapi/guides/v4/ (ten-book blocks; returned unique-market charges; odds/event endpoints; provider quota headers)

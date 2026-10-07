# The Odds API v4 normalization fixtures

The JSON files in this directory are unchanged HTTP response bodies captured from The Odds API on 2026-09-21. Do not hand-edit or normalize them; provider quirks are intentional test input.

| File | Request purpose | SHA-256 |
| --- | --- | --- |
| `nfl_featured_source_ids_t1.json` | One NFL event; `h2h,spreads,totals`; DraftKings, FanDuel, BetMGM, Pinnacle; `includeSids=true`; T1 snapshot for a future sequential-price fixture | `249169debe1ffb1f0c4aba805825446bf99ba307a99e6d07730a7112d1dff10d` |
| `soccer_three_way.json` | One EPL event; `h2h`; DraftKings, FanDuel, BetMGM; contains home, away, and draw outcomes | `9be50307b458e19e52c2d734de3a8114dadf2161d6648a4103327acaa79d2429` |
| `nfl_player_pass_tds.json` | One NFL event; `player_pass_tds`; DraftKings; `includeSids=true`; contains player descriptions, Over/Under outcomes, and points | `0266a824b8548702a6c823d9900ef7d0d1ab90387d7ae9d557210c638deab18b` |

The captured response bodies intentionally contain no API key. Request URLs and credentials are not stored in these fixtures.

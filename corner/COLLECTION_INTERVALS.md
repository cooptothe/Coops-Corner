# Scheduled collection forecast — October 20, 2026

## Final owner scope

8 a.m.–midnight America/Chicago, including the November DST change.
Main leagues: >6 hours to the next game hourly; 2–6 hours every 15 minutes;
final 2 hours every 5 minutes. One league request captures its main board:
when several games overlap, its closest upcoming game determines its cadence.
Additional markets: every 2 minutes in the final hour, existing 50-event/day
and 30,000-credit/day safeguards retained. Props: >6 hours hourly; 2–6 hours
every 5 minutes; final 2 hours every minute. No scheduled NCAA football,
men's basketball or women's basketball props. College main/additional markets
remain. Dormant exchange groups remain disabled; no history collector enabled.

## Schedule evidence

Free ESPN public scoreboard queries were downloaded for each day October 21
through December 1, 2026. Fifteen non-tennis league queries per day succeeded;
UFC and ATP/WTA used available tournament/card range responses. Event IDs were
deduplicated within each league. October 21–November 20 Central contains 3,187
listed non-tennis events; November UTC contains 4,116. The raw public schedule
lookup also returned nine ATP and seventeen WTA tournaments overlapping the
initial period. Tournaments are not individual matches: future draws cannot
be enumerated reliably now. UFC cards do not enumerate every MMA promotion.
Schedules can be revised, playoff games are conditional, and some start times
are unconfirmed. Public events do not prove provider book/market availability.
No paid odds or historical requests were made for this research.

Sources (publisher-operated public endpoints):
https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard
https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard
https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard
https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard
https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard
https://site.api.espn.com/apis/site/v2/sports/basketball/womens-college-basketball/scoreboard
Other soccer, MLB, WNBA and MMA paths are recorded in the exported inventory.
Billing: https://the-odds-api.com/liveapi/guides/v4/
Provider refresh rates: https://the-odds-api.com/sports-odds-data/update-intervals.html

## Full November quota-cycle forecast

| Component | Credits |
|---|---:|
| Pro props, every configured key returned on every planned poll | 1,433,880 |
| Main stress envelope: 82 expanded keys, all 16 hours, every 5 minutes | 1,416,960 |
| Additional: maximum 50 games/day, 30 polls/game, 5 keys | 225,000 |
| Metadata allowance (actual discovery currently zero charge) | 500,000 |
| Lab historical allowance (not activated) | 100,000 |
| Total spending envelope | 3,675,840 |
| Total with another 20% added to props | 3,962,616 |
| Protected reserve, outside spending envelope | 1,500,000 |

The 82-key main envelope deliberately overstates the configured schedule and
ignores the new slower distant-game bands. Even this envelope fits existing
main 7.9M/props 5M allocations. No budget migration, reset or extra purchase is
needed. Existing usage remains charged; all pool/reserve guards remain.
The next-month span crosses the November 1 UTC quota reset; both October's
remaining dates and the whole November cycle were simulated separately.
The original November assumptions produced a much larger NCAA props bill;
the final forecast excludes all three NCAA categories explicitly.

Peak modeled near-start *pro props* events: 23 (October 28, 22:30 UTC).
A serial worker still depends on HTTP/database latency, publication backlog,
quarantines and discovery time. Cadences are minimum due intervals, not a
latency SLA. No actual VPS load test for this new schedule is claimed.

## Freshness and rollout

Owner update: all scheduled source-age ceilings are 30 minutes (1,800 seconds).
Neither receipt nor replay re-dates provider prices. Source age and capture age
must both remain under that ceiling. Prices five minutes or older are marked
"Verify odds"; display is not proof the edge still exists at the sportsbook.
Withdrawals, started games and reader failures still remove results immediately.
Existing expired snapshots are not rewritten or resurrected; the new ceiling
applies to new captures after rollout. Hourly distant main polling can still
have gaps after 30 minutes, as explicitly requested by the owner’s age limit.
Strict CLV evidence windows are unchanged, so slower main polling may leave
more bets without a qualifying closing sample.

The worker's existing cycle/activation expires at November 1 UTC. This patch
does not auto-reset usage or silently bind a new cycle. A fresh provider quota
verification and explicit November binding/approval are still required before
that boundary. The forecast is not evidence that rollover is already set up.

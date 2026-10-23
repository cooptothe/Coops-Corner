# Live game-state filters

Play and Pause describe ESPN-reported game state, separately from sportsbook line availability. Missing odds never establish halftime or a timeout. The existing Odds API captures do not provide an authoritative game clock/stoppage field used by this application.

The Premium authenticated API enriches saved odds using a shared background ESPN cache. No browser calls ESPN directly. Fixed league paths, numeric event IDs, strict home/away matching and a three-hour start-time tolerance prevent accidental joins. Unsupported or unmatched events remain unknown and appear only under All games.

Scoreboards and matched-event summaries refresh at most every 15 seconds per process while authenticated live views are being polled. At most four requests run concurrently, with 32 pending slots, bounded cache size, timeouts, no redirects and a 4MB response limit. Reads return immediately with cached status; upstream failures never block the odds API or collector. This consumes no Odds API credits and leaves odds cadence, caps and premium authorization unchanged.

Explicit halftime, intermission, period breaks, timeout, delay and suspension statuses qualify for Pause. A play-by-play timeout qualifies only when it is the latest play and has a wallclock no older than 45 seconds; a later play clears it. Status expires after 30 seconds without a successful refresh. Finished and not-started ESPN matches lose live opportunities; fresh odds rules remain independently enforced. Delayed public data cannot prove the instantaneous state of play or that a sportsbook will accept a bet. Short stoppages can be missed between polls.

The app uses plain labels and shared SVG navigation, external-link, close, selection and play/pause icons. The existing logo and brand palette remain intact.

Source checked October 23, 2026: https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard and /summary?event=401909848. The observed summary contains status.type, displayClock, and plays with type.text and wallclock. Public endpoints have no guaranteed SLA; unavailable data is displayed as unknown, never fabricated.

## UI review
All twelve reviewed routes (EV, Props, Arbitrage, Middles, Schedule, Promo, Lab, Tracker, Account, Help, login and invitation) fit a 319px browser viewport: document content/client width both 304px with a vertical scrollbar. The mobile arbitrage calculator also fit. Actual tool components were rendered against synthetic data, not a live wagering session. Real ESPN NBA data was checked separately and the parser recognized Halftime. Physical iPhone Safari and all real book slip acceptance remain deployment checks.

Compact virtualized cards use measured heights, so long names and expanded content grow without clipping or overlapping adjacent rows. Normal synthetic arbitrage cards measured about 235px versus the former fixed 400px; middles about 267px versus 376px. A stress case with long team names expanded to 425px without clipping or overlap. Text is wrapped rather than hidden. Full sportsbook outcomes and reference details remain accessible.

Long instructional copy is centralized at /help with search and tool anchors. The same ten navigation destinations, ordering, labels, SVG icons and active state are shared by workspace, Lab, Tracker, Account and Help. Essential error/status labels, payment terms and action confirmations remain in context. No global performance/Safari certification is implied by the local review.

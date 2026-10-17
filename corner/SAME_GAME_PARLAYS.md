# Same-game parlays

Parlay mode now accepts different markets and players from the same game, as well
as mixtures of same-game groups and other games. The sportsbook, eight-leg limit,
start-time, duplicate and lay restrictions remain. Repeated/contradictory picks
from the same player/market are rejected conservatively, including alternate lines.

Same-game combinations never multiply standalone odds or individual EV estimates.
Combined odds and return are shown as “Get quote at sportsbook”. Copy the selections
or follow individual book links to build the combination in the sportsbook's SGP
builder. Automated full-slip SGP links are unavailable; ordinary cross-game
FanDuel links are preserved. Book eligibility and correlation pricing are not
asserted from single-leg quotes. No provider requests or activation changes.

After actual placement, enter the accepted combined American odds and time in
the existing tracking form. The tracker stores those accepted parent odds, counts
stake and return once, and preserves leg-level results. Voids/pushes continue to
require the actual sportsbook return instead of invented repricing.

Staging acceptance: add two different players from one game at the same book;
check the SGP label and absence of a multiplied payout; add another game's leg
and verify SGP+; remove repeated-game legs and verify the cross-game estimate
returns. Refresh prices and test withdrawn legs. Only record wagers that were
actually placed, using the sportsbook's combined quote.

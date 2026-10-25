import type { View } from "./contracts";
export const GUIDES: Record<View, [string, string]> = {
  positive_ev: [
    "Find and review an EV bet",
    "Fair prices use all eligible matching books with sport and market weights, excluding the target itself. These weights are policy priors, not proven predictive accuracy. Narrow the feed by event time, EV range, odds, and sportsbook. Select a bet to review its reference prices and size a stake. Open its sportsbook link to review the available price; log it only after placing it yourself.",
  ],
  props: [
    "Find a player prop",
    "Choose a sport and player market. Estimates remove margin from complete two-sided reference prices. EV includes modeled fees. App default uses the lower of power and proportional estimates; the devig dropdown selects a different margin model. Method comparisons show sensitivity, not a confidence interval. One-sided props can use automatically estimated margins from complete prices at two other reference books in the same event and prop market; these results are labeled as modeled. The target can be one-sided. All supported books can supply references, weighted by sport and market policy; the target is excluded and at least two other eligible books are required. DFS sources remain excluded. The Player props feed requires Novig, FanDuel or Pinnacle among the actual references; any one qualifies. These three have equal top policy weights, normalized over available complete reference prices. This display rule does not change probabilities. Check the final price and payout at the book. Filtering never triggers a provider request.",
  ],
  arbitrage: [
    "Compare both sides",
    "Select an opportunity to see both legs, required stakes, and modeled profit after supported straight-bet commissions. Quotes with unresolved fees do not create opportunities. Confirm final prices, fees and settlement at each book before placing either leg.",
  ],
  middle: [
    "Understand the middle",
    "Select a pair of lines to see the double-win window and what happens outside it. The calculator shows the cost when the middle misses; it does not predict how often the middle will land.",
  ],
  games: [
    "Explore upcoming games",
    "Choose a league or search for a team. Compare the available moneyline, spread, and total, then open the sportsbook link for that exact selection. Event times use your device's local time; Today uses Central time.",
  ],
  promo: [
    "Convert a sportsbook offer",
    "Choose the offer type and enter its terms. Compare hedge options and inspect the calculator's payout in each outcome. Token face value and withdrawable cash are shown separately.",
  ],
};
export const TOOL_NOTES: Record<string, string[]> = {
  props: [
    "Anytime touchdown (ATD) and anytime goalscorer (ATG) props can be priced when two other reference books quote both Yes and No for that exact player. The target only needs the offered side; it does not need its own opposite quote. A Yes-only list does not reveal the margin: several players can score in the same game. Otherwise, one-sided props are priced automatically when two other reference books have enough complete prices in this event and prop market to estimate their margins. Each book needs three other players. Results are labeled as modeled; EV uses the larger observed margin as a sensitivity check. This is not a calibrated win rate or a confidence bound. Select No limit for market width when the opposite price is unavailable.",
    "When paired prices and observed margin samples are unavailable, automatic mode uses a provisional 10% overround assumption with a 20% stress scenario. The displayed EV uses the more conservative scenario after supported fees. Rows are marked Modeled and appear only for a positive estimated edge that meets your minimum EV. These percentages are policy assumptions, not fitted margins or guaranteed profit.",
    "Requires two other cash-book references on the exact selection. The feed only shows bets with Novig, FanDuel or Pinnacle among those references; any one is sufficient. Caesars and Fanatics replace the former DFS sources. Fees still apply. Integer lines are conditional on no push.",
    "All supported books may contribute matching reference prices. Their influence depends on the sport and market: NBA props emphasize FanDuel; markets with limited evidence use balanced, conservative priors. These are provisional policy weights, not measured accuracy rankings. Each row shows the weights actually used; the offered sportsbook never prices its own bet.",
    "Win chance is an estimate; higher chance does not mean higher EV. Whole-number lines are conditional on no push unless a settlement model is supplied.",
  ],
  positive_ev: [
    "Win chance is an estimate; higher chance does not mean higher EV. Whole-number lines are conditional on no push unless a settlement model is supplied.",
    "Adjust the EV or market-width limits, re-enable books, or wait for the next scheduled capture. Bets need at least two sharp books pricing the same line.",
  ],
  middle: [
    "Raise the max miss cost, re-enable books, leagues or markets, or wait for the next scheduled capture. A middle needs two books quoting different lines on the same game.",
  ],
  promo: [
    "If the cash bet loses, you get its stake back as a bonus bet. This is the share of that refund you expect to turn into cash once you convert it (about 60–80%).",
  ],
  tracker: [
    "Log bets from the +EV and Player props tools (they carry their edge) and settle them. Over a few hundred bets, realized profit should track expected value.",
    "Use Record bet in any tool to record a play with its odds, edge and teams, or log one by hand. Deposits on the Bankroll tab let Kelly size bets against your real balances.",
  ],
  live: [
    "ESPN game state updates every 15 seconds and may lag play. Missing sportsbook odds do not indicate a stoppage. Unconfirmed states appear only under All games.",
  ],
};

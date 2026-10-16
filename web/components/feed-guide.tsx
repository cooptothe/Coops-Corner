import type { View } from "../lib/contracts";

const GUIDES: Record<View, [string, string]> = {
  positive_ev: [
    "Find and review an EV bet",
    "Narrow the feed by event time, EV range, odds, and sportsbook. Select a bet to review its reference prices and size a stake. Open its sportsbook link to review the available price; log it only after placing it yourself.",
  ],
  props: [
    "Find a player prop",
    "Choose a sport and player market, then fetch prop odds if the feed is empty. Use the EV and market-width sliders to narrow results. Select a player to review the bet and stake calculator. Fetching odds uses API credits; changing filters does not.",
  ],
  arbitrage: [
    "Compare both sides",
    "Select an opportunity to see both legs, required stakes, and modeled profit. Check each price and any exchange fees before placing either leg. Record the legs after placement to keep your tracker accurate.",
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

export function FeedGuide({ view }: { view: View }) {
  const [title, description] = GUIDES[view];
  return (
    <details className="feed-guide">
      <summary>How to use this view</summary>
      <div>
        <strong>{title}</strong>
        <p>{description}</p>
        <p className="exposure-legend">
          <span className="exposure-dot related" /> Yellow: an open bet on the
          same player, team, or event in another market.{" "}
          <span className="exposure-dot same-market" /> Red: an open bet on this
          market, including another line or sportsbook.
        </p>
      </div>
    </details>
  );
}

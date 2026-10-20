import type { View } from "../lib/contracts";

const GUIDES: Record<View, [string, string]> = {
  positive_ev: [
    "Find and review an EV bet",
    "Narrow the feed by event time, EV range, odds, and sportsbook. Select a bet to review its reference prices and size a stake. Open its sportsbook link to review the available price; log it only after placing it yourself.",
  ],
  props: [
    "Find a player prop",
    "Choose a sport and player market. Estimates remove margin from complete two-sided reference prices. EV includes modeled fees and uses the lower of power and proportional estimates; this is model sensitivity, not a confidence interval. One-sided props can use automatically estimated margins from complete prices at two other reference books in the same event and prop market; these results are labeled as modeled. The target can be one-sided. Caesars and Fanatics can supply cash-price references; DFS sources are excluded. Check the final price and payout at the book. Filtering never triggers a provider request.",
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

export function FeedGuide({ view }: { view: View }) {
  const [title, description] = GUIDES[view];
  return (
    <details className="feed-guide">
      <summary>How to use this view</summary>
      <div>
        <strong>{title}</strong>
        <p>{description}</p>
        <p>
          On the beta’s scheduled feed, main odds target hourly updates more
          than six hours before the league’s next game, 15 minutes from two to
          six hours, and five minutes in the final two hours. Additional markets
          target two minutes in the final hour. Pro player props target five
          minutes from two to six hours and one minute in the final two hours;
          NCAA props are not collected. Main quotes expire after six minutes of
          source age, other standard quotes after three, so slower polling can
          leave gaps. Queues and provider delays can slow updates. Confirm every
          price at the sportsbook before placing a bet.
        </p>
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

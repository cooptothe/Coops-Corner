import { test } from "node:test";
import assert from "node:assert/strict";
import { renderToStaticMarkup } from "react-dom/server";
import { ScheduleQuote } from "../components/schedule-quote";
import { StoreContext } from "../components/settings-provider";
import { SettingsStore } from "../lib/settings-store";
import { buildGameLines } from "../lib/schedule";
import type { Quote } from "../lib/contracts";

const api = {
  save: async () => undefined,
  savePreset: async () => {
    throw new Error("unused");
  },
  deletePreset: async () => undefined,
};
const future = new Date(Date.now() + 3600000).toISOString();
function render(
  links: { event?: string; market?: string; outcome?: string } | null,
  startsAt = future,
  state = "",
) {
  const store = new SettingsStore(
    { tools: { account: { state } }, presets: {} },
    api,
  );
  return renderToStaticMarkup(
    <StoreContext.Provider value={store}>
      <ScheduleQuote
        market="spreads"
        side="home"
        price={{
          quoteId: "q",
          bookId: "polymarket",
          decimal: 2.1,
          point: -3.5,
          links,
        }}
        bookName={() => "Polymarket"}
        startsAt={startsAt}
      />
    </StoreContext.Provider>,
  );
}
test("schedule price and book share a clickable market with safe new-tab behavior", () => {
  const html = render({ market: "https://polymarket.com/event/game" });
  assert.ok(html.includes('href="https://polymarket.com/event/game"'));
  assert.ok(html.includes('class="sched-price-book"'));
  assert.ok(html.includes('rel="noopener noreferrer"'));
  assert.ok(html.includes("Polymarket"));
});
test("missing links and started games stay readable without an active link", () => {
  assert.ok(!render(null).includes("<a "));
  const html = render(
    { event: "https://polymarket.com/event/game" },
    new Date(Date.now() - 1000).toISOString(),
  );
  assert.ok(!html.includes("<a "));
  assert.ok(html.includes("game started"));
});
test("state-dependent links use the saved state or show the existing state picker", () => {
  const links = { event: "https://sports.{state}.betmgm.com/events/1" };
  assert.ok(render(links).includes("Choose your state"));
  assert.ok(
    render(links, future, "il").includes(
      "https://sports.il.betmgm.com/events/1",
    ),
  );
});
test("schedule retains links from the winning quote rather than another sportsbook", () => {
  const quotes = ["home", "away"].map(
    (side) =>
      ({
        id: side,
        game_id: "g",
        contract_id: "c",
        market_key: "h2h",
        sportsbook_id: "polymarket",
        side,
        decimal_odds: "2.1",
        point: null,
        links: { market: `https://polymarket.com/${side}` },
      }) as Quote,
  );
  assert.deepEqual(
    buildGameLines(quotes, () => true).get("g")?.h2h?.sides.home.links,
    quotes[0].links,
  );
});

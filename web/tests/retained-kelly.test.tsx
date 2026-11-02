import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { KellyWidget, type KellyVm } from "../components/kelly-widget";
import { StoreContext } from "../components/settings-provider";
import { SettingsStore } from "../lib/settings-store";

test("a disappeared open bet can still be recorded while invalid sizing stays disabled", () => {
  const vm: KellyVm = {
    id: "saved",
    sportKey: "basketball_nba",
    matchup: "Away at Home",
    market: "Totals",
    line: "Over 182.5",
    ev: "0.1",
    bookLabel: "DraftKings",
    odds: "-110",
    decimalOdds: "1.90909",
    lay: false,
    startsAt: "2026-01-01T00:00:00Z",
    links: { event: "https://sportsbook.draftkings.com/event/123" },
  };
  const store = new SettingsStore(null, {
    save: async () => undefined,
    savePreset: async () => {
      throw Error("unused");
    },
    deletePreset: async () => undefined,
  });
  const render = (bankroll: string) =>
    renderToStaticMarkup(
      <StoreContext.Provider value={store}>
        <KellyWidget
          vm={vm}
          bankroll={bankroll}
          multiplier="0.25"
          setBankroll={() => {}}
          setMultiplier={() => {}}
          onClose={() => {}}
          onLogged={() => {}}
          unavailable
        />
      </StoreContext.Provider>,
    );
  const html = render("1000");
  assert.match(html, /No longer in the feed/);
  assert.match(html, /href="https:\/\/sportsbook.draftkings.com\/event\/123"/);
  assert.match(html, /<button class="button kelly-bet">Record bet<\/button>/);
  assert.match(
    render("invalid"),
    /<button class="button kelly-bet" disabled="">Record bet<\/button>/,
  );
});

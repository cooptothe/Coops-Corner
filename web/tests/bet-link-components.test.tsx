import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { BetLinkButton, LegLinks } from "../components/bet-link";
import { StoreContext } from "../components/settings-provider";
import { SettingsStore } from "../lib/settings-store";

const api = {
  save: async () => undefined,
  savePreset: async () => {
    throw new Error("unused");
  },
  deletePreset: async () => undefined,
};
const render = (node: React.ReactNode, state?: string) => {
  const store = new SettingsStore(
    state ? { tools: { account: { state } }, presets: {} } : null,
    api,
  );
  return renderToStaticMarkup(
    <StoreContext.Provider value={store}>{node}</StoreContext.Provider>,
  );
};
const future = new Date(Date.now() + 3600_000).toISOString();
const past = new Date(Date.now() - 3600_000).toISOString();
const fanduel = {
  outcome:
    "https://sportsbook.fanduel.com/addToBetslip?marketId=1&selectionId=2",
};
const betmgm = {
  event: "https://sports.{state}.betmgm.com/en/sports/events/1",
};

test("a betslip link opens in a new tab without leaking the referrer", () => {
  const html = render(
    <BetLinkButton links={fanduel} bookLabel="FanDuel" startsAt={future} />,
  );
  assert.match(html, /href="https:\/\/sportsbook\.fanduel\.com\/addToBetslip/);
  assert.match(html, /target="_blank"/);
  assert.match(html, /rel="noopener noreferrer"/);
  assert.match(html, /Bet on FanDuel/);
});

test("there is a disabled button when the sportsbook gave no link", () => {
  const html = render(
    <BetLinkButton links={null} bookLabel="FanDuel" startsAt={future} />,
  );
  assert.match(html, /disabled/);
  assert.match(html, /No FanDuel link/);
  assert.doesNotMatch(html, /<a /);
});

test("a started game or a dropped bet removes the link", () => {
  const started = render(
    <BetLinkButton links={fanduel} bookLabel="FanDuel" startsAt={past} />,
  );
  assert.match(started, /game started/);
  assert.doesNotMatch(started, /href=/);
  const dropped = render(
    <BetLinkButton
      links={fanduel}
      bookLabel="FanDuel"
      startsAt={future}
      unavailable
    />,
  );
  assert.match(dropped, /no longer available/);
  assert.doesNotMatch(dropped, /href=/);
});

test("a state link asks for the state until one is chosen", () => {
  const asks = render(
    <BetLinkButton links={betmgm} bookLabel="BetMGM" startsAt={future} />,
  );
  assert.match(asks, /<select/);
  assert.doesNotMatch(asks, /href=/);
  const opens = render(
    <BetLinkButton links={betmgm} bookLabel="BetMGM" startsAt={future} />,
    "nj",
  );
  assert.match(opens, /href="https:\/\/sports\.nj\.betmgm\.com\//);
});

test("the compact link renders only when there is somewhere to go", () => {
  const some = render(
    <BetLinkButton compact links={fanduel} bookLabel="FanDuel" />,
  );
  assert.match(some, /bet-link-compact/);
  assert.equal(
    render(<BetLinkButton compact links={null} bookLabel="FanDuel" />),
    "",
  );
  assert.equal(
    render(
      <BetLinkButton
        compact
        links={fanduel}
        bookLabel="FanDuel"
        startsAt={past}
      />,
    ),
    "",
  );
});

test("calculator legs share one state selector", () => {
  const html = render(
    <LegLinks
      startsAt={future}
      legs={[
        { links: betmgm, bookLabel: "BetMGM", label: "Over" },
        {
          links: fanduel,
          bookLabel: "FanDuel",
          label: "Under",
          stake: "10.00",
        },
      ]}
    />,
  );
  assert.equal((html.match(/<select/g) ?? []).length, 1);
  assert.match(html, /Choose your state for BetMGM/);
  assert.match(html, /Bet on FanDuel/);
});

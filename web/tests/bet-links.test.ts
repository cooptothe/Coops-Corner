import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  hasLinks,
  linkBlock,
  linkLabel,
  resolveLink,
  safeUrl,
  validState,
} from "../lib/bet-links";

const FD = {
  outcome:
    "https://sportsbook.fanduel.com/addToBetslip?marketId=42.613592434&selectionId=3050859",
  event: "https://sportsbook.fanduel.com/basketball/wnba/game-36151344",
};
const MGM = {
  outcome:
    "https://sports.{state}.betmgm.com/en/sports?options=19984576-1563634753-2310737301&type=Single",
  event: "https://sports.{state}.betmgm.com/en/sports/events/game-19984576",
};
const RIVERS = {
  outcome:
    "https://{state}.betrivers.com/?page=sportsbook#event/1029333399?coupon={pickType}|4366462176|{wagerAmount}",
  event: "https://{state}.betrivers.com/?page=sportsbook#event/1029333399",
};
const NOVIG = {
  outcome: "https://novig.com/events/01a1/oddsapi/{wager}",
  event: "https://novig.com/event-markets/01a1",
};

describe("resolveLink", () => {
  it("uses Polymarket US for stored links while preserving the market path", () => {
    assert.equal(resolveLink({ market: "https://polymarket.com/event/game?side=yes#market" }).url,
      "https://polymarket.us/event/game?side=yes#market");
    assert.equal(resolveLink({ event: "https://polymarket.us/event/game" }).url,
      "https://polymarket.us/event/game");
    assert.equal(resolveLink({ event: "https://polymarket.com.evil.test/event/game" }).url,
      "https://polymarket.com.evil.test/event/game");
  });
  it("prefers the betslip link, then the market, then the game", () => {
    assert.deepEqual(resolveLink(FD), {
      url: FD.outcome,
      kind: "betslip",
      needsState: false,
    });
    assert.equal(
      resolveLink({
        market: "https://sportsbook.fanduel.com/m",
        event: FD.event,
      }).kind,
      "market",
    );
    assert.equal(resolveLink({ event: FD.event }).kind, "game");
    assert.deepEqual(resolveLink(null), {
      url: null,
      kind: null,
      needsState: false,
    });
    assert.deepEqual(resolveLink({}), {
      url: null,
      kind: null,
      needsState: false,
    });
  });

  it("fills the user's state into the host", () => {
    const r = resolveLink(MGM, { state: "nj" });
    assert.equal(r.kind, "betslip");
    assert.match(
      r.url!,
      /^https:\/\/sports\.nj\.betmgm\.com\/en\/sports\?options=/,
    );
    assert.match(
      resolveLink(RIVERS, { state: "pa", stake: "10" }).url!,
      /^https:\/\/pa\.betrivers\.com\//,
    );
  });

  it("without a state, says one is needed instead of guessing", () => {
    const r = resolveLink(MGM);
    assert.equal(r.url, null);
    assert.equal(r.needsState, true);
    assert.equal(resolveLink(MGM, { state: "zz" }).needsState, true); // not a real state
    assert.equal(resolveLink(MGM, { state: "NJ" }).needsState, true); // must be the lower-case code
  });

  it("falls back to a link that needs nothing, but still reports the better one", () => {
    const r = resolveLink({ outcome: MGM.outcome, event: FD.event });
    assert.equal(r.kind, "game");
    assert.equal(r.url, FD.event);
    assert.equal(r.needsState, true);
  });

  it("prefills the stake only where the link takes one", () => {
    assert.equal(
      resolveLink(NOVIG, { stake: "54.81" }).url,
      "https://novig.com/events/01a1/oddsapi/54.81",
    );
    assert.equal(
      resolveLink(NOVIG, { stake: "25.00" }).url?.endsWith("/oddsapi/25"),
      true,
    );
    // No usable stake: the betslip link needs one, so the game page is offered instead.
    for (const stake of [undefined, "", "0", "abc", "-5", "1e3", "12.345"]) {
      const r = resolveLink(NOVIG, { stake });
      assert.equal(r.kind, "game", String(stake));
      assert.equal(r.url, NOVIG.event);
    }
    const rivers = resolveLink(RIVERS, { state: "nj", stake: "10" });
    assert.match(rivers.url!, /coupon=single\|4366462176\|10$/);
  });

  it("never turns an unknown placeholder or a bad scheme into a link", () => {
    assert.equal(
      resolveLink({ event: "https://sportsbook.fanduel.com/{evil}" }).url,
      null,
    );
    assert.equal(
      resolveLink({ event: "http://sportsbook.fanduel.com/x" }).url,
      null,
    );
    assert.equal(resolveLink({ event: "javascript:alert(1)" }).url, null);
    assert.equal(
      resolveLink({ event: "https://user:pw@sportsbook.fanduel.com/x" }).url,
      null,
    );
    assert.equal(
      resolveLink({ event: "https://sportsbook.fanduel.com/x y" }).url,
      null,
    );
  });
});

describe("safeUrl", () => {
  it("accepts plain https addresses only", () => {
    assert.equal(
      safeUrl("https://sportsbook.fanduel.com/a?b=c"),
      "https://sportsbook.fanduel.com/a?b=c",
    );
    for (const bad of [
      "http://a.com",
      "//a.com",
      "https://a.com:8443/x",
      "https://localhost/x",
      "https://a.com/<x>",
      "https://a.com/" + "x".repeat(2100),
      "not a url",
      "",
    ])
      assert.equal(safeUrl(bad), null, bad.slice(0, 40));
  });
});

describe("helpers", () => {
  it("labels by how exact the link is", () => {
    assert.equal(linkLabel("betslip", "FanDuel"), "Bet on FanDuel");
    assert.equal(linkLabel("market", "FanDuel"), "Open FanDuel market");
    assert.equal(linkLabel("game", "FanDuel"), "Open game on FanDuel");
  });
  it("validates states and detects links", () => {
    assert.equal(validState("nj"), "nj");
    assert.equal(validState("xx"), "");
    assert.equal(validState(5), "");
    assert.equal(hasLinks({ event: "x" }), true);
    assert.equal(hasLinks({}), false);
    assert.equal(hasLinks(undefined), false);
  });
  it("blocks links to games that have started or bets that are gone", () => {
    const now = Date.parse("2026-10-08T20:00:00Z");
    assert.equal(linkBlock("2026-10-08T19:59:00Z", false, now), "started");
    assert.equal(linkBlock("2026-10-08T21:00:00Z", false, now), null);
    assert.equal(linkBlock("2026-10-08T21:00:00Z", true, now), "unavailable");
    assert.equal(linkBlock(undefined, false, now), null);
    assert.equal(linkBlock("garbage", false, now), null);
  });
});

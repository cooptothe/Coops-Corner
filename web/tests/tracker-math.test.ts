import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { CashEntry, TrackerBet, TrackerState } from "../lib/tracker-api";
import {
  bookBalances,
  bookCode,
  bookLabel,
  dailySeries,
  drawdown,
  kellyCents,
  kpis,
  ledger,
  parseDollars,
  profit,
  sparkPath,
  toWin,
  totals,
} from "../lib/tracker-math";
import {
  EMPTY_FILTERS,
  initialView,
  matchesFilters,
  orderBets,
  trackerReducer,
} from "../lib/tracker-state";

let n = 0;
function bet(over: Partial<TrackerBet> = {}): TrackerBet {
  n++;
  return {
    id: `b${n}`,
    client_key: `k${n}`,
    group_id: null,
    created_at: "2026-03-01T12:00:00+00:00",
    placed_at: "2026-03-01T12:00:00+00:00",
    strategy: "ev",
    sport_key: "basketball_nba",
    matchup: "Celtics at Heat",
    starts_at: null,
    market: "Moneyline",
    selection: "Celtics",
    book: "fanduel",
    odds: "2",
    stake_cents: 10000,
    stake_type: "cash",
    status: "pending",
    returned_cents: null,
    settled_at: null,
    fair_prob: null,
    ev_ratio: null,
    ref: {},
    clv: null,
    notes: "",
    ...over,
  };
}
const won = (over: Partial<TrackerBet> = {}) =>
  bet({
    status: "won",
    returned_cents: 20000,
    settled_at: "2026-03-02T12:00:00+00:00",
    ...over,
  });
const lost = (over: Partial<TrackerBet> = {}) =>
  bet({
    status: "lost",
    returned_cents: 0,
    settled_at: "2026-03-03T12:00:00+00:00",
    ...over,
  });
function cash(over: Partial<CashEntry>): CashEntry {
  n++;
  return {
    id: `c${n}`,
    client_key: `ck${n}`,
    occurred_at: "2026-03-01T09:00:00+00:00",
    kind: "deposit",
    amount_cents: 100000,
    book: "fanduel",
    to_book: null,
    note: "",
    ...over,
  };
}
const state = (bets: TrackerBet[], c: CashEntry[] = []): TrackerState => ({
  bets,
  cash: c,
});

describe("single bets", () => {
  it("profit counts the stake for cash and winnings only for bonus bets", () => {
    assert.equal(profit(won()), 10000);
    assert.equal(profit(lost()), -10000);
    assert.equal(profit(bet()), null);
    const bonusWin = bet({
      stake_type: "bonus",
      status: "won",
      returned_cents: 10000,
    });
    assert.equal(profit(bonusWin), 10000);
    const bonusLoss = bet({
      stake_type: "bonus",
      status: "lost",
      returned_cents: 0,
    });
    assert.equal(profit(bonusLoss), 0);
    assert.equal(toWin(bet({ odds: "2.5" })), 15000);
  });

  it("parses dollars strictly", () => {
    assert.equal(parseDollars("$1,250.50"), 125050);
    assert.equal(parseDollars("12.345"), null);
    assert.equal(parseDollars("1e3"), null);
    assert.equal(parseDollars(""), null);
  });

  it("maps sportsbook names to codes and back", () => {
    assert.equal(bookCode("FanDuel"), "fanduel");
    assert.equal(bookCode("theScore Bet"), "thescore_bet");
    assert.equal(bookCode("Hard Rock Bet"), "hard_rock_bet");
    assert.equal(bookCode("Ref Pinnacle"), "ref_pinnacle");
    assert.equal(bookLabel("draftkings"), "DraftKings");
    assert.equal(bookLabel("some_new_book"), "Some New Book");
  });
});

describe("balances and the ledger", () => {
  const s = state(
    [won({ book: "fanduel" }), bet({ book: "draftkings", stake_cents: 5000 })],
    [
      cash({ kind: "deposit", book: "fanduel", amount_cents: 100000 }),
      cash({ kind: "deposit", book: "vault", amount_cents: 50000 }),
      cash({
        kind: "transfer",
        book: "vault",
        to_book: "draftkings",
        amount_cents: 20000,
      }),
      cash({ kind: "withdrawal", book: "fanduel", amount_cents: 30000 }),
    ],
  );

  it("derives per-book balances and a total that includes pending stakes", () => {
    const rows = bookBalances(s);
    const by = Object.fromEntries(rows.map((r) => [r.book, r]));
    // fanduel: +1000 deposit -100 stake +200 return -300 withdrawal
    assert.equal(by.fanduel.liquid, 80000 + 0);
    assert.equal(by.draftkings.liquid, 20000 - 5000);
    assert.equal(by.draftkings.pending, 5000);
    assert.equal(by.vault.liquid, 30000);
    const t = totals(rows);
    assert.equal(t.bankroll, 80000 + 15000 + 5000 + 30000);
    assert.equal(t.pending, 5000);
  });

  it("moving cash between books never changes the total", () => {
    const before = totals(bookBalances(s)).bankroll;
    const moved = state(s.bets, [
      ...s.cash,
      cash({
        kind: "transfer",
        book: "fanduel",
        to_book: "vault",
        amount_cents: 10000,
      }),
    ]);
    assert.equal(totals(bookBalances(moved)).bankroll, before);
  });

  it("builds a running net-bankroll ledger in order", () => {
    const rows = ledger(s);
    assert.equal(
      rows[rows.length - 1].running,
      totals(bookBalances(s)).bankroll,
    );
    const kinds = rows.map((r) => r.kind);
    assert.ok(
      kinds.includes("WAGER_DEDUCTION") && kinds.includes("WAGER_PAYOUT"),
    );
    const transfer = rows.find((r) => r.kind === "BOOK_TRANSFER")!;
    const index = rows.indexOf(transfer);
    assert.equal(transfer.running, rows[index - 1].running);
    // A deduction moves cash to pending: bankroll is unchanged until the bet settles.
    const place = rows.find((r) => r.kind === "WAGER_DEDUCTION")!;
    assert.equal(place.running, rows[rows.indexOf(place) - 1]?.running ?? 0);
  });
});

describe("kpis", () => {
  const bets = [
    won(),
    lost({ settled_at: "2026-03-03T12:00:00+00:00" }),
    won({
      stake_cents: 5000,
      returned_cents: 10000,
      settled_at: "2026-03-04T12:00:00+00:00",
    }),
    bet({ stake_cents: 2500 }),
    bet({
      status: "push",
      returned_cents: 10000,
      settled_at: "2026-03-05T12:00:00+00:00",
    }),
  ];

  it("totals profit, ROI and the W-L-P record", () => {
    const k = kpis(bets);
    assert.equal(k.pnl, 10000 - 10000 + 5000 + 0);
    assert.equal(k.staked, 10000 + 10000 + 5000 + 10000);
    assert.equal(k.roi, 5000 / 35000);
    assert.deepEqual([k.wins, k.losses, k.pushes], [2, 1, 1]);
    assert.equal(k.pending, 1);
    assert.equal(k.pendingExposure, 2500);
    assert.deepEqual(k.spark, [10000, 0, 5000, 5000]);
  });

  it("windows settled bets by settle date", () => {
    const since = new Date("2026-03-04T00:00:00+00:00").getTime();
    const k = kpis(bets, since);
    assert.equal(k.settled, 2);
    assert.equal(k.pnl, 5000);
  });

  it("measures closing-line value only over bets that have one", () => {
    const withClv = [
      won({ clv: { pct: "0.04", at: "x" } }),
      won({ clv: { pct: "-0.02", at: "x" } }),
      won({ clv: { pct: "0.06", at: "x" } }),
      won({ clv: { pct: null, reason: "no close", at: "x" } }),
      won(),
    ];
    const k = kpis(withClv);
    assert.equal(k.clvMeasured, 3);
    assert.equal(k.clvTotal, 5);
    assert.equal(k.clvBeat, 2 / 3);
    assert.ok(Math.abs((k.clvAvg ?? 0) - 0.08 / 3) < 1e-12);
    assert.equal(kpis([won()]).clvBeat, null);
  });

  it("has no ROI before anything settles and a sparkline needs two points", () => {
    assert.equal(kpis([bet()]).roi, null);
    assert.equal(sparkPath([5], 100, 20), "");
    assert.match(sparkPath([5, -5, 10], 100, 20), /^M0\.0,/);
  });
});

describe("history", () => {
  const s = state(
    [
      won({ settled_at: "2026-03-02T12:00:00+00:00", ev_ratio: "0.05" }),
      lost({ settled_at: "2026-03-04T12:00:00+00:00", ev_ratio: "0.05" }),
      lost({ settled_at: "2026-03-05T12:00:00+00:00" }),
    ],
    [
      cash({
        kind: "deposit",
        amount_cents: 100000,
        occurred_at: "2026-03-01T12:00:00+00:00",
      }),
      cash({
        kind: "withdrawal",
        amount_cents: 20000,
        occurred_at: "2026-03-05T12:00:00+00:00",
      }),
    ],
  );
  const series = dailySeries(s, new Date("2026-03-06T12:00:00"));

  it("has one point per day with carried-forward totals", () => {
    assert.deepEqual(
      series.map((p) => p.day),
      [
        "2026-03-01",
        "2026-03-02",
        "2026-03-03",
        "2026-03-04",
        "2026-03-05",
        "2026-03-06",
      ],
    );
    assert.equal(series[0].bankroll, 100000);
    assert.equal(series[1].bankroll, 110000);
    assert.equal(series[2].bankroll, 110000);
    // 1100 - 100 (loss) - 100 (loss) - 200 withdrawal
    assert.equal(series[5].bankroll, 70000);
    assert.equal(series[5].pnl, -10000);
  });

  it("tracks expected value against realized results on edge bets only", () => {
    const last = series[5];
    assert.equal(last.evExpected, 10000 * 0.05 * 2);
    assert.equal(last.evPnl, 10000 - 10000);
  });

  it("measures drawdown on profit, not on withdrawals", () => {
    const d = drawdown(series);
    assert.equal(d.maxCents, 20000);
    assert.equal(d.currentCents, 20000);
    assert.equal(d.peakDay, "2026-03-02");
    assert.equal(d.troughDay, "2026-03-05");
    assert.ok(d.maxPct != null && Math.abs(d.maxPct - 20000 / 110000) < 1e-12);
    assert.deepEqual(dailySeries(state([])), []);
    assert.equal(drawdown([]).maxCents, 0);
  });
});

describe("kelly sizing", () => {
  it("uses (edge / (odds - 1)) x bankroll x scalar", () => {
    // 5% edge at 2.0 -> 5% full Kelly; quarter-Kelly of $1,000 = $12.50
    assert.equal(kellyCents(0.05, 2, 100000, 0.25), 1250);
    assert.equal(kellyCents(0.05, 2, 100000, 1), 5000);
  });
  it("suggests nothing without an edge, odds or bankroll", () => {
    assert.equal(kellyCents(0, 2, 100000, 0.5), 0);
    assert.equal(kellyCents(-0.1, 2, 100000, 0.5), 0);
    assert.equal(kellyCents(0.05, 1, 100000, 0.5), 0);
    assert.equal(kellyCents(0.05, 2, 0, 0.5), 0);
    assert.equal(kellyCents(0.05, 2, -500, 0.5), 0);
  });
});

describe("reducer", () => {
  const a = won();
  const b = bet();

  it("loads, upserts and removes by id", () => {
    let v = trackerReducer(initialView, {
      type: "LOAD",
      bets: [a, b],
      cash: [],
    });
    assert.equal(v.bets.length, 2);
    v = trackerReducer(v, {
      type: "BET_UPSERT",
      bets: [{ ...b, status: "lost", returned_cents: 0 }],
    });
    assert.equal(v.bets.find((x) => x.id === b.id)?.status, "lost");
    assert.equal(v.bets.length, 2);
    v = trackerReducer(v, { type: "BET_REMOVE", id: a.id });
    assert.deepEqual(
      v.bets.map((x) => x.id),
      [b.id],
    );
  });

  it("keeps row identity when a reload brings identical data", () => {
    const v1 = trackerReducer(initialView, {
      type: "LOAD",
      bets: [a, b],
      cash: [],
    });
    const v2 = trackerReducer(v1, {
      type: "LOAD",
      bets: [{ ...a }, { ...b, notes: "x" }],
      cash: [],
    });
    assert.equal(v2.bets[0], v1.bets[0]);
    assert.notEqual(v2.bets[1], v1.bets[1]);
  });

  it("live updates touch only the changed entries and no-op when nothing changed", () => {
    const view = (detail: string) => ({
      state: "in" as const,
      detail,
      score: {},
      progress: null,
      suggest: null,
    });
    let v = trackerReducer(initialView, {
      type: "LIVE_UPDATE",
      live: { x: view("Q1"), y: view("Q2") },
    });
    const same = trackerReducer(v, {
      type: "LIVE_UPDATE",
      live: { x: view("Q1"), y: view("Q2") },
    });
    assert.equal(same, v);
    const next = trackerReducer(v, {
      type: "LIVE_UPDATE",
      live: { x: view("Q1"), y: view("Q3") },
    });
    assert.equal(next.live.x, v.live.x);
    assert.notEqual(next.live.y, v.live.y);
    v = trackerReducer(next, { type: "LIVE_UPDATE", live: { x: view("Q1") } });
    assert.deepEqual(Object.keys(v.live), ["x"]);
  });

  it("filters by book, league, status, strategy and search words", () => {
    const f = (x: Partial<typeof EMPTY_FILTERS>) => ({
      ...EMPTY_FILTERS,
      ...x,
    });
    const prop = bet({
      strategy: "prop",
      book: "draftkings",
      selection: "Jayson Tatum Over 5.5 REB",
      sport_key: "basketball_nba",
    });
    assert.equal(matchesFilters(prop, f({ books: ["fanduel"] })), false);
    assert.equal(matchesFilters(prop, f({ books: ["draftkings"] })), true);
    assert.equal(
      matchesFilters(prop, f({ leagues: ["icehockey_nhl"] })),
      false,
    );
    assert.equal(matchesFilters(prop, f({ strategy: "ev" })), false);
    assert.equal(matchesFilters(prop, f({ status: "active" })), true);
    assert.equal(matchesFilters(prop, f({ status: "settled" })), false);
    assert.equal(matchesFilters(prop, f({ query: "tatum reb" })), true);
    assert.equal(matchesFilters(prop, f({ query: "tatum ast" })), false);
    assert.equal(matchesFilters(won(), f({ status: "won" })), true);
    assert.equal(matchesFilters(won(), f({ status: "lost" })), false);
  });

  it("lists pending bets first by game time, then settled newest first", () => {
    const later = bet({ starts_at: "2026-03-09T00:00:00+00:00" });
    const sooner = bet({ starts_at: "2026-03-08T00:00:00+00:00" });
    const old = won({ settled_at: "2026-03-01T00:00:00+00:00" });
    const recent = lost({ settled_at: "2026-03-07T00:00:00+00:00" });
    assert.deepEqual(
      orderBets([old, later, recent, sooner]).map((x) => x.id),
      [sooner.id, later.id, recent.id, old.id],
    );
  });
});

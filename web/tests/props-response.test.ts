import { selectPropDevig } from "../lib/devig-selection";
import { passesPropEdge } from "../lib/prop-edge";
import { test } from "node:test";
import assert from "node:assert/strict";
import { parsePropsStatus, propDecimal } from "../lib/props-response";
import { compareDecimal } from "../../frontend/format.mjs";
const valid = {
  id: "q",
  event_id: "game",
  sport_key: "basketball_nba",
  home: "Home",
  away: "Away",
  starts_at: "2030-01-01T18:00:00Z",
  market_key: "player_points",
  market_label: "Points",
  group: "Scoring",
  player: "Player",
  side: "Over",
  book: "draftkings",
  point: "22.5",
  price: "2.1",
  ev: "0.05",
  fair_probability: "0.5",
  sharps: ["fanduel", "pinnacle"],
  observed_at: null,
};
test("empty props, including a legacy bets-only response, retain safe feed metadata", () => {
  for (const payload of [
    { bets: [] },
    { bets: null, sports: [], markets: {} },
    { sports: [], markets: {} },
  ]) {
    const s = parsePropsStatus(payload);
    assert.deepEqual(s.bets, []);
    assert.deepEqual(s.sports, []);
    assert.deepEqual(s.markets, {});
    assert.equal(s.manual_fetch_enabled, false);
    assert.equal(s.invalid_bets, 0);
  }
});
test("scientific Decimal output is expanded exactly before sorting or formatting", () => {
  assert.throws(() => compareDecimal("0E-28", "0"), /Invalid decimal/);
  for (const [value, plain] of [
    ["0E-28", "0"],
    ["1.234567890123456789E-7", "0.0000001234567890123456789"],
    ["-4.25E+2", "-425"],
    ["1E+2", "100"],
  ])
    assert.equal(propDecimal(value), plain);
  const s = parsePropsStatus({
    bets: [
      {
        ...valid,
        ev: "0E-28",
        devig_comparisons: [
          { method: "power", probability: "5E-1", ev: "1E-27" },
        ],
      },
    ],
  });
  assert.equal(compareDecimal(s.bets![0].ev, "0"), 0);
  assert.equal(
    s.bets![0].devig_comparisons![0].ev,
    "0.000000000000000000000000001",
  );
  assert.throws(() => propDecimal("1E999"));
  assert.throws(() => propDecimal("NaN"));
});
test("one invalid prop cannot crash or discard valid rows", () => {
  const s = parsePropsStatus({
    bets: [
      valid,
      { ...valid, id: "bad", price: "1" },
      { ...valid, id: "bad-date", starts_at: "bad" },
      { ...valid, id: "null-sharps", sharps: null },
      { ...valid, id: "bad-decimal", ev: "NaN" },
      null,
      valid,
    ],
  });
  assert.deepEqual(
    s.bets!.map((b) => b.id),
    ["q"],
  );
  assert.equal(s.invalid_bets, 6);
});
test("service errors and malformed lists are not disguised as an empty feed", () => {
  for (const value of [
    null,
    {},
    [],
    { error: "Unavailable", bets: [] },
    { bets: "bad" },
  ])
    assert.throws(() => parsePropsStatus(value));
});

test("Worst case zero EV becomes an empty positive-EV feed rather than a sorting exception", () => {
  const bet = parsePropsStatus({
    bets: [
      {
        ...valid,
        devig_comparisons: [
          { method: "worst_case", probability: "0.476190476190", ev: "0E-12" },
        ],
      },
    ],
  }).bets![0];
  const selected = selectPropDevig(bet, "worst_case")!;
  assert.equal(compareDecimal(selected.ev, "0"), 0);
  assert.equal(passesPropEdge(selected.ev, "0"), false);
  const lower = selectPropDevig(
    parsePropsStatus({
      bets: [
        {
          ...valid,
          devig_comparisons: [
            { method: "worst_case", probability: "0.45", ev: "-0.055" },
          ],
        },
      ],
    }).bets![0],
    "worst_case",
  )!;
  assert.equal(passesPropEdge(lower.ev, "0"), false);
});

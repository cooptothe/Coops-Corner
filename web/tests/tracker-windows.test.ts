import assert from "node:assert/strict";
import { test } from "node:test";
import {
  performanceBounds,
  matchesPerformanceWindow,
} from "../lib/tracker-windows";
import { kpis } from "../lib/tracker-math";
import type { TrackerBet } from "../lib/tracker-api";

test("today and yesterday use local midnight with an exclusive upper boundary", () => {
  const now = new Date(2026, 9, 22, 15, 30).getTime();
  const midnight = new Date(2026, 9, 22).getTime();
  assert.deepEqual(performanceBounds(1, now), [midnight, now + 1]);
  assert.deepEqual(performanceBounds(-1, now), [
    new Date(2026, 9, 21).getTime(),
    midnight,
  ]);
  const bet = (at: number) =>
    ({
      status: "won",
      stake_type: "cash",
      stake_cents: 100,
      returned_cents: 200,
      settled_at: new Date(at).toISOString(),
      clv: null,
    }) as TrackerBet;
  assert.equal(
    kpis([bet(midnight - 1), bet(midnight)], ...performanceBounds(-1, now))
      .settled,
    1,
  );
  assert.equal(
    kpis([bet(midnight - 1), bet(midnight)], ...performanceBounds(1, now))
      .settled,
    1,
  );
});

test("three days includes today and the two preceding local dates", () => {
  const now = new Date(2026, 2, 9, 12).getTime();
  assert.deepEqual(performanceBounds(3, now), [
    new Date(2026, 2, 7).getTime(),
    now + 1,
  ]);
});

test("six calendar months clamps to month end and includes the boundary", () => {
  const now = new Date(2026, 7, 31, 12).getTime();
  assert.deepEqual(performanceBounds(180, now), [
    new Date(2026, 1, 28, 12).getTime(),
    now + 1,
  ]);
  assert.deepEqual(performanceBounds(0, now), [null, null]);
  assert.deepEqual(performanceBounds(7, now), [now - 7 * 86400000, now + 1]);
});

test("yesterday ledger uses event dates, not placement or settlement day", () => {
  const now = new Date(2026, 9, 22, 12).getTime();
  const placed_at = new Date(2026, 9, 21, 9).toISOString();
  const at = (day: number, hour = 12) => ({
    placed_at,
    starts_at: new Date(2026, 9, day, hour).toISOString(),
  });
  assert.equal(matchesPerformanceWindow(at(21), -1, now), true);
  assert.equal(matchesPerformanceWindow(at(22), -1, now), false);
  assert.equal(matchesPerformanceWindow(at(20), -1, now), false);
  assert.equal(matchesPerformanceWindow(at(22, 0), -1, now), false);
  assert.equal(matchesPerformanceWindow(at(22, 23), 1, now), true);
  assert.equal(matchesPerformanceWindow(at(23, 0), 1, now), false);
  assert.equal(
    matchesPerformanceWindow({ placed_at, starts_at: null }, -1, now),
    true,
  );
  assert.equal(matchesPerformanceWindow(at(22), null, now), true);
  assert.equal(matchesPerformanceWindow(at(20), 3, now), true);
  assert.equal(matchesPerformanceWindow(at(19), 3, now), false);
});

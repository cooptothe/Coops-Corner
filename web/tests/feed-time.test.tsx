import { test } from "node:test";
import assert from "node:assert/strict";
import { renderToStaticMarkup } from "react-dom/server";
import { matchesFeedTime, type TimeFilter } from "../lib/feed-time";
import { FeedTimeFilter } from "../components/feed-time-filter";

const now = Date.parse("2026-10-11T18:00:00Z");
const at = (hours: number) => new Date(now + hours * 3600000).toISOString();

test("rolling windows exclude started games and include the exact upper boundary", () => {
  for (const [filter, hours] of [
    ["8h", 8],
    ["24h", 24],
    ["3d", 72],
    ["1w", 168],
  ] as [TimeFilter, number][]) {
    assert.equal(matchesFeedTime(at(-1), filter, now), false);
    assert.equal(matchesFeedTime(at(0), filter, now), false);
    assert.equal(matchesFeedTime(at(hours), filter, now), true);
    assert.equal(matchesFeedTime(at(hours + 0.001), filter, now), false);
    assert.equal(matchesFeedTime("", filter, now), false);
  }
});

test("today follows Chicago midnight, including daylight saving transitions", () => {
  assert.equal(matchesFeedTime("2026-10-12T04:59:59Z", "today", now), true);
  assert.equal(matchesFeedTime("2026-10-12T05:00:00Z", "today", now), false);
  const fallback = Date.parse("2026-11-01T05:30:00Z");
  assert.equal(
    matchesFeedTime("2026-11-02T05:59:59Z", "today", fallback),
    true,
  );
  assert.equal(
    matchesFeedTime("2026-11-02T06:00:00Z", "today", fallback),
    false,
  );
});

test("default preserves the existing feed without imposing a time restriction", () => {
  assert.equal(matchesFeedTime(at(500), "default", now), true);
  assert.equal(matchesFeedTime("", "default", now), true);
});

test("buttons expose all choices and mark the active filter accessibly", () => {
  const html = renderToStaticMarkup(
    <FeedTimeFilter value="8h" onChange={() => {}} />,
  );
  assert.equal((html.match(/<button /g) ?? []).length, 6);
  assert.equal((html.match(/aria-pressed="true"/g) ?? []).length, 1);
  for (const label of [
    "Default",
    "Upcoming (Next 8 Hours)",
    "Today Only",
    "Next 24 hours",
    "Within 3 days",
    "1 week",
  ])
    assert.ok(html.includes(label));
});

import assert from "node:assert/strict";
import { test } from "node:test";
import { quoteAgeStatus } from "../lib/quote-age";

test("stored prices request verification after five minutes and expire at thirty", () => {
  const now = Date.parse("2026-10-20T22:00:00Z");
  const at = (seconds: number) => new Date(now - seconds * 1000).toISOString();
  assert.equal(quoteAgeStatus(at(299), now), "recent");
  assert.equal(quoteAgeStatus(at(300), now), "review");
  assert.equal(quoteAgeStatus(at(1799), now), "review");
  assert.equal(quoteAgeStatus(at(1800), now), "expired");
  assert.equal(quoteAgeStatus(null, now), "unknown");
  assert.equal(quoteAgeStatus("invalid", now), "unknown");
  assert.equal(quoteAgeStatus(at(-10), now), "unknown");
});

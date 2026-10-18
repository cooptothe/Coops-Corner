import { test } from "node:test";
import assert from "node:assert/strict";
import {
  announceOddsUpdated,
  subscribeOddsUpdated,
  ODDS_STORAGE_KEY,
} from "../lib/odds-updates";
import { refreshOdds, refreshProps, reloadTools } from "../lib/refresh-api";
import { sharedPages, invalidateSharedPages } from "../lib/api";

test("one update notifies every feed, other tabs refresh on storage signal, and cleanup works", () => {
  const stored: [string, string][] = [];
  const target = Object.assign(new EventTarget(), {
    localStorage: {
      setItem: (key: string, value: string) => stored.push([key, value]),
    },
  });
  const counts = [0, 0, 0, 0];
  const stop = counts.map((_, i) =>
    subscribeOddsUpdated(() => counts[i]++, target),
  );
  announceOddsUpdated(target);
  assert.deepEqual(counts, [1, 1, 1, 1]);
  assert.equal(stored[0][0], ODDS_STORAGE_KEY);
  target.dispatchEvent(
    Object.assign(new Event("storage"), { key: ODDS_STORAGE_KEY }),
  );
  assert.deepEqual(counts, [2, 2, 2, 2]);
  target.dispatchEvent(
    Object.assign(new Event("storage"), { key: "unrelated" }),
  );
  stop.forEach((fn) => fn());
  announceOddsUpdated(target);
  assert.deepEqual(counts, [2, 2, 2, 2]);
});

test("main fetch and prop fetch each use one provider-facing POST and one shared rebuild", async () => {
  const oldFetch = globalThis.fetch;
  const requests: string[] = [];
  globalThis.fetch = async (url, init) => {
    requests.push(`${init?.method} ${url}`);
    return new Response(JSON.stringify({ refreshed: true, bets: [] }), {
      status: 200,
    });
  };
  try {
    await refreshOdds(["basketball_nba"]);
    await reloadTools(); // main fetch controller's existing publication step
    assert.deepEqual(requests, [
      "POST /api/refresh/v1/odds",
      "POST /api/v1/catalog/reload",
    ]);
    requests.length = 0;
    await refreshProps("basketball_nba", ["player_threes_alternate"], 1);
    assert.deepEqual(requests, [
      "POST /api/refresh/v1/props",
      "POST /api/v1/catalog/reload",
    ]);
    requests.length = 0;
    globalThis.fetch = async (url) => {
      requests.push(String(url));
      return new Response(JSON.stringify({ error: "Fetch denied" }), {
        status: 403,
      });
    };
    await assert.rejects(
      refreshProps("basketball_nba", ["player_threes"], 1),
      /Fetch denied/,
    );
    assert.deepEqual(requests, ["/api/refresh/v1/props"]);
  } finally {
    globalThis.fetch = oldFetch;
  }
});

test("shared lists are invalidated without another provider request", async () => {
  const oldFetch = globalThis.fetch;
  let reads = 0;
  globalThis.fetch = async () => {
    reads++;
    return new Response(
      JSON.stringify({
        meta: {
          format: "corner.product_api/1",
          data_mode: "database",
          production_authorized: false,
          availability_verified: false,
          snapshot_id: "test",
        },
        data: {
          items: [{ id: reads }],
          total: 1,
          offset: 0,
          limit: 100,
          next_offset: null,
        },
      }),
    );
  };
  try {
    invalidateSharedPages();
    const signal = new AbortController().signal;
    await sharedPages("quotes", "test", signal);
    await sharedPages("quotes", "test", signal);
    assert.equal(reads, 1);
    announceOddsUpdated(new EventTarget());
    await sharedPages("quotes", "test", signal);
    assert.equal(reads, 2);
  } finally {
    globalThis.fetch = oldFetch;
    invalidateSharedPages();
  }
});

test("feeds are notified only after a successful rebuild, never on failed rebuild or initial boot", async () => {
  const target = new EventTarget();
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const oldFetch = globalThis.fetch;
  Object.defineProperty(globalThis, "window", {
    value: target,
    configurable: true,
  });
  let notices = 0;
  const stop = subscribeOddsUpdated(() => notices++, target);
  try {
    globalThis.fetch = async () => new Response("{}", { status: 200 });
    await reloadTools(false);
    assert.equal(notices, 0);
    await reloadTools();
    assert.equal(notices, 1);
    globalThis.fetch = async () => new Response("{}", { status: 503 });
    await assert.rejects(reloadTools(), /shared feeds could not be rebuilt/);
    assert.equal(notices, 1);
  } finally {
    stop();
    globalThis.fetch = oldFetch;
    if (previousWindow)
      Object.defineProperty(globalThis, "window", previousWindow);
    else Reflect.deleteProperty(globalThis, "window");
  }
});

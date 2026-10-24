import { test } from "node:test";
import assert from "node:assert/strict";
import { loadToolSnapshot } from "../lib/tool-snapshot.ts";
const signal = () => new AbortController().signal;
function reply(snapshot: string, data: unknown) {
  return Response.json({
    meta: {
      format: "corner.product_api/1",
      data_mode: "database",
      production_authorized: false,
      availability_verified: false,
      snapshot_id: snapshot,
    },
    data,
  });
}

test("feed loads only page-related quotes and shares prefetch with its mounted view", async () => {
  const old = globalThis.fetch;
  let requests = 0;
  globalThis.fetch = async (input) => {
    const url = new URL(String(input), "http://localhost");
    assert.equal(url.pathname, "/api/v1/tools/positive_ev");
    assert.equal(url.searchParams.get("include_quotes"), "true");
    requests++;
    const offset = Number(url.searchParams.get("offset")),
      limit = Number(url.searchParams.get("limit"));
    const count = Math.min(limit, 300 - offset);
    return reply("bundle:1", {
      items: Array.from({ length: count }, (_, i) => ({
        id: `r${offset + i}`,
        quote_ids: ["q1", "q2"],
      })),
      quotes: [{ id: "q1" }, { id: "q2" }],
      offset,
      limit,
      total: 300,
      next_offset: offset + limit < 300 ? offset + limit : null,
    });
  };
  try {
    const [a, b] = await Promise.all([
      loadToolSnapshot("positive_ev", "bundle:1", signal()),
      loadToolSnapshot("positive_ev", "bundle:1", signal()),
    ]);
    assert.equal(a.rows.length, 300);
    assert.equal(a.quotes.length, 2);
    assert.equal(requests, 2);
    assert.deepEqual(a, b);
    assert.notEqual(a.rows, b.rows);
  } finally {
    globalThis.fetch = old;
  }
});

test("empty feeds finish without fetching unrelated quotes", async () => {
  const old = globalThis.fetch;
  globalThis.fetch = async (input) => {
    assert.ok(String(input).includes("/tools/middle?"));
    return reply("bundle:empty", {
      items: [],
      quotes: [],
      offset: 0,
      limit: 250,
      total: 0,
      next_offset: null,
    });
  };
  try {
    assert.deepEqual(
      await loadToolSnapshot("middle", "bundle:empty", signal()),
      { rows: [], quotes: [] },
    );
  } finally {
    globalThis.fetch = old;
  }
});

test("missing referenced quotes are errors rather than silently disappearing opportunities", async () => {
  const old = globalThis.fetch;
  globalThis.fetch = async () =>
    reply("bundle:missing", {
      items: [{ id: "r", quote_ids: ["absent"] }],
      quotes: [],
      offset: 0,
      limit: 250,
      total: 1,
      next_offset: null,
    });
  try {
    await assert.rejects(
      loadToolSnapshot("arbitrage", "bundle:missing", signal()),
      /incomplete quotes/,
    );
  } finally {
    globalThis.fetch = old;
  }
});

test("devig selections are sent on all pages and do not share the wrong cache", async () => {
  const old = globalThis.fetch;
  const methods: string[] = [];
  globalThis.fetch = async (input) => {
    const p = new URL(String(input), "http://localhost").searchParams;
    methods.push(p.get("devig_method")!);
    return reply("bundle:methods", {
      items: [],
      quotes: [],
      offset: 0,
      limit: 250,
      total: 0,
      next_offset: null,
    });
  };
  try {
    for (const method of ["power", "worst_case"])
      await loadToolSnapshot("positive_ev", "bundle:methods", signal(), {
        params: { devig_method: method },
      });
    assert.deepEqual(methods, ["power", "worst_case"]);
  } finally {
    globalThis.fetch = old;
  }
});

test("snapshot changes while loading cannot produce a mixed feed", async () => {
  const old = globalThis.fetch;
  globalThis.fetch = async () =>
    reply("bundle:different", {
      items: [],
      quotes: [],
      offset: 0,
      limit: 250,
      total: 0,
      next_offset: null,
    });
  try {
    await assert.rejects(
      loadToolSnapshot("positive_ev", "bundle:requested", signal()),
      { code: "snapshot_changed" },
    );
  } finally {
    globalThis.fetch = old;
  }
});

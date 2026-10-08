import { test } from "node:test";
import assert from "node:assert/strict";
import { allPages, sharedPages } from "../lib/api.ts";

const meta = {
  format: "corner.product_api/1",
  data_mode: "fixture",
  snapshot_id: "fixture:1",
  production_authorized: false,
  availability_verified: false,
};

interface Served {
  requests: number[];
  widest: number;
  limits: Set<string>;
}

// A server holding `total` numbered rows, served the way the real one pages them.
function serve(total: number, shape: (page: object) => object = (p) => p) {
  const served: Served = { requests: [], widest: 0, limits: new Set() };
  let active = 0;
  globalThis.fetch = async (url) => {
    const params = new URL(String(url), "http://localhost").searchParams;
    const offset = Number(params.get("offset"));
    const limit = Number(params.get("limit"));
    served.requests.push(offset);
    served.limits.add(String(limit));
    active++;
    served.widest = Math.max(served.widest, active);
    await new Promise((resolve) => setTimeout(resolve, 5));
    active--;
    const items = Array.from(
      { length: Math.max(0, Math.min(limit, total - offset)) },
      (_, i) => offset + i,
    );
    const end = offset + limit;
    return new Response(
      JSON.stringify({
        meta: { ...meta, snapshot_id: params.get("snapshot_id") },
        data: shape({
          items,
          total,
          offset,
          limit,
          next_offset: end < total ? end : null,
        }),
      }),
    );
  };
  return served;
}
const signal = () => new AbortController().signal;

test("pages after the first are fetched side by side and joined in order", async () => {
  const old = globalThis.fetch;
  try {
    const served = serve(1234);
    const items = await allPages<number>("games", "fixture:1", signal());
    assert.deepEqual(
      items,
      Array.from({ length: 1234 }, (_, i) => i),
    );
    assert.equal(served.requests.length, 13);
    assert.ok(served.widest > 1, "pages were requested one at a time");
    assert.ok(served.widest <= 6, "more requests in flight than connections");
  } finally {
    globalThis.fetch = old;
  }
});

test("a larger page size is sent as asked and every page is used", async () => {
  const old = globalThis.fetch;
  try {
    const served = serve(2500);
    const items = await allPages<number>("quotes", "fixture:1", signal(), {
      limit: 1000,
      maxOffset: 100000,
    });
    assert.equal(items.length, 2500);
    assert.deepEqual([...served.limits], ["1000"]);
    assert.deepEqual(
      [...served.requests].sort((a, b) => a - b),
      [0, 1000, 2000],
    );
  } finally {
    globalThis.fetch = old;
  }
});

test("a single page needs a single request", async () => {
  const old = globalThis.fetch;
  try {
    const served = serve(40);
    assert.equal((await allPages("games", "fixture:1", signal())).length, 40);
    assert.deepEqual(served.requests, [0]);
  } finally {
    globalThis.fetch = old;
  }
});

test("inconsistent pages are rejected instead of joined", async () => {
  const old = globalThis.fetch;
  try {
    // a total that moves between pages
    serve(350, (page) => ({
      ...page,
      total: (page as { offset: number }).offset === 0 ? 350 : 351,
    }));
    await assert.rejects(
      allPages("games", "fixture:1", signal()),
      /Invalid page/,
    );
    // a short page in the middle
    serve(350, (page) => {
      const p = page as { offset: number; items: number[] };
      return p.offset === 100 ? { ...p, items: p.items.slice(1) } : p;
    });
    await assert.rejects(
      allPages("games", "fixture:1", signal()),
      /Invalid page/,
    );
    // rows that do not add up to the total
    serve(350, (page) => {
      const p = page as { offset: number; items: number[] };
      return p.offset === 300 ? { ...p, items: p.items.slice(1) } : p;
    });
    await assert.rejects(
      allPages("games", "fixture:1", signal()),
      /Invalid page/,
    );
  } finally {
    globalThis.fetch = old;
  }
});

test("a list longer than the server can page is refused", async () => {
  const old = globalThis.fetch;
  try {
    serve(20000);
    await assert.rejects(
      allPages("games", "fixture:1", signal()),
      /exceeds the client page bound/,
    );
  } finally {
    globalThis.fetch = old;
  }
});

test("a server without totals is still read cursor by cursor", async () => {
  const old = globalThis.fetch;
  try {
    const served = serve(250, (page) => {
      const { total: _total, ...rest } = page as { total: number };
      return rest;
    });
    const items = await allPages<number>("games", "fixture:1", signal());
    assert.equal(items.length, 250);
    assert.equal(served.widest, 1);
    assert.deepEqual(served.requests, [0, 100, 200]);
  } finally {
    globalThis.fetch = old;
  }
});

test("asking twice for one snapshot's list fetches it once, and hands out copies", async () => {
  const old = globalThis.fetch;
  try {
    const served = serve(150);
    const [a, b] = await Promise.all([
      sharedPages<number>("tools/a", "shared:1", signal()),
      sharedPages<number>("tools/a", "shared:1", signal()),
    ]);
    assert.equal(served.requests.length, 2);
    assert.deepEqual(a, b);
    assert.notEqual(a, b);
    a.length = 0; // one caller changing its list must not change another's
    assert.equal(
      (await sharedPages("tools/a", "shared:1", signal())).length,
      150,
    );
    assert.equal(served.requests.length, 2);
    await sharedPages("tools/a", "shared:2", signal());
    assert.equal(served.requests.length, 4); // a new snapshot is fetched again
  } finally {
    globalThis.fetch = old;
  }
});

test("one caller leaving does not cancel the shared fetch for the other", async () => {
  const old = globalThis.fetch;
  try {
    serve(150);
    const leaving = new AbortController();
    const stays = sharedPages<number>("tools/b", "shared:3", signal());
    const left = sharedPages<number>("tools/b", "shared:3", leaving.signal);
    leaving.abort();
    await assert.rejects(left, (error: Error) => error.name === "AbortError");
    assert.equal((await stays).length, 150);
  } finally {
    globalThis.fetch = old;
  }
});

test("a failed shared fetch is forgotten, so a retry asks again", async () => {
  const old = globalThis.fetch;
  try {
    globalThis.fetch = async () => new Response("down", { status: 500 });
    await assert.rejects(sharedPages("tools/c", "shared:4", signal()));
    const served = serve(10);
    assert.equal(
      (await sharedPages("tools/c", "shared:4", signal())).length,
      10,
    );
    assert.equal(served.requests.length, 1);
  } finally {
    globalThis.fetch = old;
  }
});

import { test } from "node:test";
import assert from "node:assert/strict";
import { loadSnapshotQuotes } from "../lib/snapshot-quotes.ts";
import { invalidateSharedPages } from "../lib/api.ts";

const meta = {
  format: "corner.product_api/1",
  data_mode: "database",
  snapshot_id: "snapshot:large",
  production_authorized: false,
  availability_verified: false,
};
const books = [
  { id: "a", name: "A", commission: null },
  { id: "b", name: "B", commission: null },
];
function page(
  total: number,
  offset: number,
  limit: number,
  item: (i: number) => unknown,
) {
  return {
    items: Array.from(
      { length: Math.max(0, Math.min(limit, total - offset)) },
      (_, i) => item(i + offset),
    ),
    total,
    offset,
    limit,
    next_offset: offset + limit < total ? offset + limit : null,
  };
}
function reply(data: unknown, snapshot = meta.snapshot_id) {
  return Response.json({ meta: { ...meta, snapshot_id: snapshot }, data });
}

test("a quote snapshot beyond 100k loads every book without exceeding six requests in flight", async () => {
  const old = globalThis.fetch;
  invalidateSharedPages();
  let active = 0,
    peak = 0;
  const partitions = new Set<string>();
  globalThis.fetch = async (input) => {
    const url = new URL(String(input), "http://localhost");
    const p = url.searchParams;
    assert.equal(p.get("snapshot_id"), meta.snapshot_id);
    const book = p.get("sportsbook_id");
    const offset = Number(p.get("offset")),
      limit = Number(p.get("limit"));
    assert.ok(offset <= 100000);
    assert.equal(limit, 1000);
    active++;
    peak = Math.max(active, peak);
    await new Promise((resolve) => setTimeout(resolve, 1));
    active--;
    if (!book)
      return reply(
        page(120001, offset, limit, (i) => ({
          id: `bulk-${i}`,
          sportsbook_id: "a",
        })),
      );
    partitions.add(book);
    return reply(
      page(book === "a" ? 60001 : 60000, offset, limit, (i) => ({
        id: `${book}-${i}`,
        sportsbook_id: book,
      })),
    );
  };
  try {
    const quotes = await loadSnapshotQuotes(
      meta.snapshot_id,
      new AbortController().signal,
      books,
    );
    assert.equal(quotes.length, 120001);
    assert.equal(new Set(quotes.map((q) => q.id)).size, 120001);
    assert.deepEqual([...partitions], ["a", "b"]);
    assert.ok(peak <= 6);
    assert.equal(quotes.filter((q) => q.sportsbook_id === "b").length, 60000);
  } finally {
    globalThis.fetch = old;
    invalidateSharedPages();
  }
});

test("a single oversized book is partitioned by game, without dropping quotes", async () => {
  const old = globalThis.fetch;
  invalidateSharedPages();
  globalThis.fetch = async (input) => {
    const url = new URL(String(input), "http://localhost"),
      p = url.searchParams;
    const offset = Number(p.get("offset")),
      limit = Number(p.get("limit"));
    assert.equal(p.get("snapshot_id"), meta.snapshot_id);
    if (url.pathname.endsWith("/quotes"))
      return reply(
        page(102000, offset, limit, (i) => ({
          id: `bulk-${i}`,
          sportsbook_id: "a",
        })),
      );
    if (url.pathname.endsWith("/games"))
      return reply(page(12, offset, limit, (i) => ({ id: `game-${i}` })));
    assert.equal(p.get("sportsbook_id"), "a");
    assert.ok(offset <= 10000);
    const game = url.pathname.split("/").at(-2);
    return reply(
      page(8500, offset, limit, (i) => ({
        id: `${game}-${i}`,
        sportsbook_id: "a",
      })),
    );
  };
  try {
    const quotes = await loadSnapshotQuotes(
      meta.snapshot_id,
      new AbortController().signal,
      books.slice(0, 1),
    );
    assert.equal(quotes.length, 102000);
    assert.equal(new Set(quotes.map((q) => q.id)).size, 102000);
  } finally {
    globalThis.fetch = old;
    invalidateSharedPages();
  }
});

test("partitioning never hides a snapshot change or returns partial success", async () => {
  const old = globalThis.fetch;
  invalidateSharedPages();
  globalThis.fetch = async (input) => {
    const p = new URL(String(input), "http://localhost").searchParams;
    if (!p.get("sportsbook_id"))
      return reply(page(120001, 0, 1000, (i) => ({ id: String(i) })));
    return reply(
      page(1, 0, 1000, (i) => ({ id: String(i), sportsbook_id: "a" })),
      "snapshot:changed",
    );
  };
  try {
    await assert.rejects(
      loadSnapshotQuotes(meta.snapshot_id, new AbortController().signal, books),
      { code: "snapshot_changed" },
    );
  } finally {
    globalThis.fetch = old;
    invalidateSharedPages();
  }
});

test("older APIs without bulk quotes still load game boards", async () => {
  const old = globalThis.fetch;
  invalidateSharedPages();
  globalThis.fetch = async (input) => {
    const url = new URL(String(input), "http://localhost"),
      p = url.searchParams;
    if (url.pathname.endsWith("/quotes"))
      return Response.json({ error: { code: "not_found" } }, { status: 404 });
    if (url.pathname.endsWith("/games"))
      return reply(page(2, 0, 100, (i) => ({ id: `g${i}` })));
    assert.equal(p.get("snapshot_id"), meta.snapshot_id);
    return reply(page(1, 0, 100, (i) => ({ id: `${url.pathname}-${i}` })));
  };
  try {
    assert.equal(
      (await loadSnapshotQuotes(meta.snapshot_id, new AbortController().signal))
        .length,
      2,
    );
  } finally {
    globalThis.fetch = old;
    invalidateSharedPages();
  }
});

import assert from "node:assert/strict";
import { test } from "node:test";
import { loadTrendOptions } from "../lib/trends-api";

async function pages(data: unknown[], run: () => Promise<void>) {
  const original = globalThis.fetch;
  let index = 0;
  globalThis.fetch = async () =>
    new Response(JSON.stringify(data[index++]), { status: 200 });
  try {
    await run();
  } finally {
    globalThis.fetch = original;
  }
}
const first = {
  contracts: [{ id: "a" }],
  snapshot_id: "s",
  total: 2,
  offset: 0,
  next_offset: 1,
};
const second = {
  contracts: [{ id: "b" }],
  snapshot_id: "s",
  total: 2,
  offset: 1,
  next_offset: null,
};
test("Lab loads the complete quote inventory across validated pages", async () => {
  await pages([first, second], async () => {
    const result = await loadTrendOptions(new AbortController().signal);
    assert.deepEqual(
      result.contracts.map((v) => v.id),
      ["a", "b"],
    );
  });
});
test("Lab rejects changed snapshots, duplicate quotes and incomplete inventories", async () => {
  for (const invalid of [
    { ...second, snapshot_id: "changed" },
    { ...second, contracts: [{ id: "a" }] },
    { ...second, contracts: [] },
    { ...first, next_offset: 0 },
  ]) {
    await pages([first, invalid], async () => {
      await assert.rejects(loadTrendOptions(new AbortController().signal));
    });
  }
});

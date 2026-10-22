import { test } from "node:test";
import assert from "node:assert/strict";
import { sharedPages, invalidateSharedPages } from "../lib/api";
import { setStorageOwner } from "../lib/user-storage";
test("same-snapshot feed cache is cleared when the signed-in account changes", async () => {
  const old = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        meta: {
          format: "corner.product_api/1",
          data_mode: "fixture",
          production_authorized: false,
          availability_verified: false,
          snapshot_id: "same",
        },
        data: {
          items: [{ id: ++calls }],
          total: 1,
          offset: 0,
          limit: 100,
          next_offset: null,
        },
      }),
    );
  try {
    invalidateSharedPages();
    const signal = new AbortController().signal;
    setStorageOwner("a");
    await sharedPages("quotes", "same", signal);
    setStorageOwner("a");
    await sharedPages("quotes", "same", signal);
    assert.equal(calls, 1);
    setStorageOwner("b");
    await sharedPages("quotes", "same", signal);
    assert.equal(calls, 2);
    setStorageOwner(null);
    await sharedPages("quotes", "same", signal);
    assert.equal(calls, 3);
  } finally {
    setStorageOwner(null);
    invalidateSharedPages();
    globalThis.fetch = old;
  }
});

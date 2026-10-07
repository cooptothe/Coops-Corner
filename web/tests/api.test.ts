import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { validateEnvelope, request, allPages, ApiError } from "../lib/api.ts";
const meta = {
  format: "corner.product_api/1",
  data_mode: "fixture",
  snapshot_id: "fixture:1",
  production_authorized: false,
  availability_verified: false,
};
test("versioned fixture envelope requires explicit safe mode", () => {
  assert.deepEqual(
    validateEnvelope({ meta, data: { items: [] } }, "fixture:1").data,
    { items: [] },
  );
  for (const key of [
    "format",
    "data_mode",
    "production_authorized",
    "availability_verified",
    "snapshot_id",
  ])
    assert.throws(
      () => validateEnvelope({ meta: { ...meta, [key]: undefined }, data: {} }),
      ApiError,
    );
});
test("snapshot drift and missing data fail closed", () => {
  assert.throws(
    () => validateEnvelope({ meta, data: {} }, "new"),
    /Snapshot changed/,
  );
  assert.throws(() => validateEnvelope({ meta }), /missing data/);
});
test("typed request sends decimal strings and bound snapshot", async () => {
  let captured: RequestInit | undefined;
  const fetcher: typeof fetch = async (_url, init) => {
    captured = init;
    return new Response(JSON.stringify({ meta, data: { ok: true } }));
  };
  await request("calculators/promo", {
    body: { face_value: "9007199254740993.01" },
    snapshot: "fixture:1",
    fetcher,
  });
  assert.equal(captured?.cache, "no-store");
  assert.equal(captured?.method, "POST");
  assert.match(String(captured?.body), /9007199254740993.01/);
});
test("non-JSON and API errors do not appear as successful zero results", async () => {
  await assert.rejects(
    request("tools/middle", { fetcher: async () => new Response("not-json") }),
    /did not return JSON/,
  );
  await assert.rejects(
    request("tools/middle", {
      fetcher: async () =>
        new Response(
          JSON.stringify({
            error: { message: "Bound mismatch", code: "bad_binding" },
          }),
          { status: 422 },
        ),
    }),
    /Bound mismatch/,
  );
});
test("pre-aborted request cannot succeed", async () => {
  const c = new AbortController();
  c.abort();
  await assert.rejects(
    request("games", {
      signal: c.signal,
      fetcher: async (_url, init) => {
        if (init?.signal?.aborted)
          throw new DOMException("Aborted", "AbortError");
        return new Response("{}");
      },
    }),
    { name: "AbortError" },
  );
});
test("paged boot gathers every page and validates monotonic cursors", async () => {
  const old = globalThis.fetch;
  try {
    globalThis.fetch = async (url) => {
      const offset = Number(
        new URL(String(url), "http://localhost").searchParams.get("offset"),
      );
      return new Response(
        JSON.stringify({
          meta,
          data: {
            items: [offset],
            offset,
            next_offset: offset === 0 ? 1 : null,
          },
        }),
      );
    };
    assert.deepEqual(
      await allPages<number>(
        "games",
        "fixture:1",
        new AbortController().signal,
      ),
      [0, 1],
    );
    globalThis.fetch = async () =>
      new Response(
        JSON.stringify({
          meta,
          data: { items: [], offset: 0, next_offset: 0 },
        }),
      );
    await assert.rejects(
      allPages("games", "fixture:1", new AbortController().signal),
      /Invalid page cursor/,
    );
  } finally {
    globalThis.fetch = old;
  }
});
test("Next public assets match original supplied brand bytes", () => {
  for (const [asset, sha] of [
    [
      "corner-logo.png",
      "0b1ebebc1e648c66a0b91283d4e907a51bd463aa8a6d6ca24543eb8592e92100",
    ],
    [
      "corner-banner.png",
      "5c4f69cd39954fe19c2905d07fe526fe741c1601eb4a5adf9d170b92e5e16529",
    ],
  ])
    assert.equal(
      createHash("sha256")
        .update(
          readFileSync(new URL(`../public/assets/${asset}`, import.meta.url)),
        )
        .digest("hex"),
      sha,
    );
});

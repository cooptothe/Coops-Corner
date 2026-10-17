import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { loadProps } from "../lib/refresh-api";

test("one-sided assumptions only reprice stored quotes with a request-scoped GET", async () => {
  const original = globalThis.fetch;
  const requests: [string, string | undefined][] = [];
  globalThis.fetch = async (url, init) => {
    requests.push([String(url), init?.method]);
    return new Response(JSON.stringify({ bets: [] }), { status: 200 });
  };
  try {
    await loadProps(undefined, "0.08");
    await loadProps();
    assert.deepEqual(requests, [
      ["/api/refresh/v1/props?one_sided_margin=0.08", "GET"],
      ["/api/refresh/v1/props", "GET"],
    ]);
  } finally {
    globalThis.fetch = original;
  }
});

test("page sources contain no known mojibake sequences", () => {
  function inspect(directory: string) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) inspect(path);
      else if (/\.(tsx?|mjs|css)$/.test(path))
        assert.doesNotMatch(
          readFileSync(path, "utf8"),
          /\u00c2|\u00c3|\u00e2\u20ac|\ufffd/,
          path,
        );
    }
  }
  for (const directory of ["components", "app", "lib", "../frontend"])
    inspect(directory);
});

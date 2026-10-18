import assert from "node:assert/strict";
import { test } from "node:test";
import config from "../next.config";

test("browser API rewrites use the two guarded loopback services, never the retired Java service", async () => {
  const rewrites = await config.rewrites!();
  assert.ok(Array.isArray(rewrites));
  assert.deepEqual(
    rewrites.map((row) => row.source),
    ["/api/refresh/v1/:path*", "/api/v1/:path*"],
  );
  for (const row of rewrites) {
    const url = new URL(row.destination.replace(":path*", "test"));
    assert.ok(["127.0.0.1", "localhost", "[::1]"].includes(url.hostname));
    assert.ok(["8765", "8766"].includes(url.port));
    assert.equal(url.protocol, "http:");
  }
});

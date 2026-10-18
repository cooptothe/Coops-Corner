import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import manifest from "../app/manifest";

test("installation manifest names real square PNG assets at the advertised sizes", () => {
  const value = manifest();
  assert.equal(value.display, "standalone");
  assert.equal(value.start_url, "/");
  assert.equal(value.scope, "/");
  assert.equal(value.name, "The Corner");
  for (const icon of value.icons ?? []) {
    const bytes = readFileSync(join("public", icon.src));
    assert.equal(bytes.subarray(1, 4).toString(), "PNG");
    assert.equal(
      `${bytes.readUInt32BE(16)}x${bytes.readUInt32BE(20)}`,
      icon.sizes,
    );
  }
});

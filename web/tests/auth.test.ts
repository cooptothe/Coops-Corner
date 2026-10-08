import assert from "node:assert/strict";
import { test } from "node:test";
import { safeNext, USERNAME_PATTERN } from "../lib/auth-api";

test("only same-site paths are followed after signing in", () => {
  assert.equal(safeNext("/tracker"), "/tracker");
  assert.equal(safeNext("/positive_ev?x=1"), "/positive_ev?x=1");
  for (const bad of [
    "https://evil.example",
    "//evil.example",
    "/\\evil.example",
    "javascript:alert(1)",
    "tracker",
    "/login",
    "",
    null,
    undefined,
  ])
    assert.equal(safeNext(bad as string | null), "/", String(bad));
});

test("the username rule matches the server's", () => {
  for (const ok of ["Coop", "a.b-c_d", "abc", "x".repeat(24), "9lives"])
    assert.ok(USERNAME_PATTERN.test(ok), ok);
  for (const bad of ["ab", "x".repeat(25), "-abc", "has space", "<b>", ""])
    assert.ok(!USERNAME_PATTERN.test(bad), bad);
});

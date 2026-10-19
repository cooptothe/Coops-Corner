import test from "node:test";
import assert from "node:assert/strict";
import { invitationToken } from "../lib/invitation-api";
test("private invitation fragments accept only bounded generated codes", () => {
  const code = "FRIEND-" + "a".repeat(43);
  assert.equal(invitationToken("#" + code), code);
  assert.equal(invitationToken("#invite=" + code), code);
  for (const invalid of [
    "#bad",
    "#" + "a".repeat(201),
    "#invite=https://evil.test",
    "#" + "a".repeat(30) + "?x=1",
  ]) {
    assert.equal(invitationToken(invalid), "");
  }
});

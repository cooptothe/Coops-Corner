import assert from "node:assert/strict";
import { test } from "node:test";
import { passesPropReferences } from "../lib/prop-references";

test("props require Novig, FanDuel or Pinnacle among the actual references", () => {
  for (const sharps of [
    ["novig", "draftkings"],
    ["fanduel", "draftkings"],
    ["pinnacle", "betmgm"],
    ["fanduel", "pinnacle"],
  ]) {
    assert.equal(passesPropReferences({ sharps }), true);
  }
  for (const sharps of [[], ["draftkings", "betmgm"]]) {
    assert.equal(passesPropReferences({ sharps }), false);
  }
  // Offering the bet at FanDuel does not make it a reference.
  const targetOnly = { book: "fanduel", sharps: ["draftkings", "betmgm"] };
  assert.equal(passesPropReferences(targetOnly), false);
  assert.equal(
    passesPropReferences({
      book: "novig",
      sharps: ["draftkings", "betmgm"],
    } as typeof targetOnly),
    false,
  );
});

import assert from "node:assert/strict";
import { test } from "node:test";
import { choice, list, sorted, text } from "../lib/settings-fields";

test("saved text is used only when it matches the pattern", () => {
  assert.equal(text("2.5", /^\d{1,2}(\.\d{1,2})?$/, "0"), "2.5");
  assert.equal(text("abc", /^\d+$/, "0"), "0");
  assert.equal(text(5, /^\d+$/, "0"), "0");
  assert.equal(text(undefined, /^\d+$/, "0"), "0");
});

test("saved lists keep only strings and numbers, bounded", () => {
  assert.deepEqual(list(["a", 2, null, { x: 1 }, ["y"]]), ["a", "2"]);
  assert.deepEqual(list("not a list"), []);
  assert.equal(list(Array.from({ length: 500 }, (_, i) => i)).length, 300);
});

test("a choice must be one of the allowed values", () => {
  assert.equal(choice("time", ["profit", "time"] as const, "profit"), "time");
  assert.equal(
    choice<string>("toString", { profit: 1, time: 2 }, "profit"),
    "profit",
  );
  assert.equal(choice("other", ["profit"] as const, "profit"), "profit");
  assert.equal(choice(3, ["profit"] as const, "profit"), "profit");
});

test("sets are saved in a stable order", () => {
  assert.deepEqual(sorted(new Set(["b", "a", "c"])), ["a", "b", "c"]);
});

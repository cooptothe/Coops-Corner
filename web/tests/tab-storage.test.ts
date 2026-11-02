import assert from "node:assert/strict";
import { test } from "node:test";
import { setStorageOwner, userTabStorage } from "../lib/user-storage";
test("tab preferences stay isolated by account and browser tab", () => {
  const previous = Object.getOwnPropertyDescriptor(
    globalThis,
    "sessionStorage",
  );
  const make = () => {
    const m = new Map<string, string>();
    return {
      getItem: (k: string) => m.get(k) ?? null,
      setItem: (k: string, v: string) => m.set(k, v),
    };
  };
  const a = make(),
    b = make();
  try {
    Object.defineProperty(globalThis, "sessionStorage", {
      configurable: true,
      value: a,
    });
    setStorageOwner("alice");
    userTabStorage.setItem("filter", "nba");
    setStorageOwner("bob");
    assert.equal(userTabStorage.getItem("filter"), null);
    setStorageOwner("alice");
    assert.equal(userTabStorage.getItem("filter"), "nba");
    Object.defineProperty(globalThis, "sessionStorage", {
      configurable: true,
      value: b,
    });
    assert.equal(userTabStorage.getItem("filter"), null);
    userTabStorage.setItem("filter", "nhl");
    Object.defineProperty(globalThis, "sessionStorage", {
      configurable: true,
      value: a,
    });
    assert.equal(userTabStorage.getItem("filter"), "nba");
    setStorageOwner(null);
    assert.equal(userTabStorage.getItem("filter"), null);
  } finally {
    setStorageOwner(null);
    if (previous) Object.defineProperty(globalThis, "sessionStorage", previous);
    else Reflect.deleteProperty(globalThis, "sessionStorage");
  }
});

import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";
import { setStorageOwner, userStorage } from "../lib/user-storage";

class Memory {
  data = new Map<string, string>();
  getItem(k: string) {
    return this.data.get(k) ?? null;
  }
  setItem(k: string, v: string) {
    this.data.set(k, v);
  }
  removeItem(k: string) {
    this.data.delete(k);
  }
}
let memory: Memory;
beforeEach(() => {
  memory = new Memory();
  (globalThis as { localStorage?: unknown }).localStorage = memory;
  setStorageOwner(null);
});

test("each account keeps its own settings in a shared browser", () => {
  setStorageOwner("ann");
  userStorage.setItem("corner.bankroll", "5000");
  setStorageOwner("bob");
  assert.equal(userStorage.getItem("corner.bankroll"), null);
  userStorage.setItem("corner.bankroll", "20");
  setStorageOwner("ann");
  assert.equal(userStorage.getItem("corner.bankroll"), "5000");
  setStorageOwner("bob");
  assert.equal(userStorage.getItem("corner.bankroll"), "20");
});

test("nothing is read or written while signed out", () => {
  userStorage.setItem("k", "v");
  assert.equal(memory.data.size, 0);
  assert.equal(userStorage.getItem("k"), null);
});

test("settings saved before accounts existed go to the first reader only", () => {
  memory.setItem("corner.kelly", "0.5");
  setStorageOwner("ann");
  assert.equal(userStorage.getItem("corner.kelly"), "0.5");
  assert.equal(memory.getItem("corner.kelly"), null);
  setStorageOwner("bob");
  assert.equal(userStorage.getItem("corner.kelly"), null);
  setStorageOwner("ann");
  assert.equal(userStorage.getItem("corner.kelly"), "0.5");
});

test("removing a setting only removes the signed-in account's copy", () => {
  setStorageOwner("ann");
  userStorage.setItem("a", "1");
  setStorageOwner("bob");
  userStorage.setItem("a", "2");
  userStorage.removeItem("a");
  setStorageOwner("ann");
  assert.equal(userStorage.getItem("a"), "1");
});

test("live and filter UI preferences survive a return visit without leaking between pages or accounts", async () => {
  const { readUiBoolean, saveUiBoolean } =
    await import("../lib/ui-preferences");
  setStorageOwner("wonya");
  saveUiBoolean("live-mode.positive_ev", true);
  saveUiBoolean("filters./positive_ev.live", false);
  assert.equal(readUiBoolean("live-mode.positive_ev", false), true);
  assert.equal(readUiBoolean("live-mode.arbitrage", false), false);
  assert.equal(readUiBoolean("filters./positive_ev.live", true), false);
  assert.equal(readUiBoolean("filters./positive_ev.pregame", true), true);
  setStorageOwner("another");
  assert.equal(readUiBoolean("live-mode.positive_ev", false), false);
  setStorageOwner("wonya");
  assert.equal(readUiBoolean("live-mode.positive_ev", false), true);
});

test("unavailable or corrupt preference storage does not break live controls", async () => {
  const { readUiBoolean, saveUiBoolean } =
    await import("../lib/ui-preferences");
  setStorageOwner("wonya");
  userStorage.setItem("corner.ui.bad", "invalid");
  assert.equal(readUiBoolean("bad", true), true);
  memory.setItem = () => {
    throw new Error("storage denied");
  };
  assert.doesNotThrow(() => saveUiBoolean("live-mode.positive_ev", true));
  memory.getItem = () => {
    throw new Error("storage denied");
  };
  assert.equal(readUiBoolean("bad", false), false);
});

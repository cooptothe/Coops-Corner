import assert from "node:assert/strict";
import { describe, it, mock } from "node:test";
import type { Preset, Settings } from "../lib/settings-api";
import { SettingsStore, canon, type SettingsApi } from "../lib/settings-store";

function fakeApi() {
  const calls = { save: [] as [string, Settings][], deleted: [] as string[] };
  let failSaves = false;
  const api: SettingsApi = {
    save: async (tool, settings) => {
      if (failSaves) throw new Error("offline");
      calls.save.push([tool, settings]);
    },
    savePreset: async (tool, name, settings) => ({
      id: `${tool}:${name.toLowerCase()}`,
      name,
      settings,
    }),
    deletePreset: async (id) => {
      calls.deleted.push(id);
    },
  };
  return { api, calls, fail: (v: boolean) => (failSaves = v) };
}

describe("canon", () => {
  it("ignores key order but not array order", () => {
    assert.equal(
      canon({ a: 1, b: { y: 2, x: 1 } }),
      canon({ b: { x: 1, y: 2 }, a: 1 }),
    );
    assert.notEqual(canon({ a: [1, 2] }), canon({ a: [2, 1] }));
  });
});

describe("settings store", () => {
  it("serves saved settings and presets instantly", () => {
    const { api } = fakeApi();
    const preset: Preset = { id: "p1", name: "Mine", settings: { x: 1 } };
    const store = new SettingsStore(
      { tools: { props: { minEv: "2" } }, presets: { props: [preset] } },
      api,
    );
    assert.deepEqual(store.get("props"), { minEv: "2" });
    assert.equal(store.get("promo"), undefined);
    assert.deepEqual(store.presets("props"), [preset]);
    assert.equal(store.presets("promo"), store.presets("middle")); // one shared empty list: stable for React
  });

  it("keeps the latest value in memory at once and saves it once, shortly after the last change", async () => {
    mock.timers.enable({ apis: ["setTimeout"] });
    try {
      const { api, calls } = fakeApi();
      const store = new SettingsStore(null, api);
      store.put("props", { minEv: "1" });
      store.put("props", { minEv: "2" });
      store.put("props", { minEv: "3" });
      assert.deepEqual(store.get("props"), { minEv: "3" });
      assert.equal(calls.save.length, 0);
      mock.timers.tick(700);
      await Promise.resolve();
      assert.deepEqual(calls.save, [["props", { minEv: "3" }]]);
      store.put("props", { minEv: "3" }); // unchanged: nothing to send
      mock.timers.tick(700);
      await Promise.resolve();
      assert.equal(calls.save.length, 1);
    } finally {
      mock.timers.reset();
    }
  });

  it("flushes pending changes immediately, for when the tab closes", async () => {
    mock.timers.enable({ apis: ["setTimeout"] });
    try {
      const { api, calls } = fakeApi();
      const store = new SettingsStore(null, api);
      store.put("promo", { type: "credit" });
      store.put("middle", { stake: "50" });
      store.flush(true);
      await Promise.resolve();
      assert.deepEqual(calls.save.map((c) => c[0]).sort(), ["middle", "promo"]);
    } finally {
      mock.timers.reset();
    }
  });

  it("reports a failed save and retries it with the next flush", async () => {
    mock.timers.enable({ apis: ["setTimeout"] });
    try {
      const { api, calls, fail } = fakeApi();
      const store = new SettingsStore(null, api);
      let notified = 0;
      store.subscribe(() => notified++);
      fail(true);
      store.put("props", { minEv: "4" });
      mock.timers.tick(700);
      await new Promise((r) => setImmediate(r));
      assert.equal(store.syncError(), "offline");
      assert.ok(notified > 0);
      assert.deepEqual(store.get("props"), { minEv: "4" }); // still kept locally
      fail(false);
      store.flush();
      await new Promise((r) => setImmediate(r));
      assert.deepEqual(calls.save, [["props", { minEv: "4" }]]);
      assert.equal(store.syncError(), null);
    } finally {
      mock.timers.reset();
    }
  });

  it("saves presets sorted by name, replaces a same-named one, and deletes", async () => {
    const { api, calls } = fakeApi();
    const store = new SettingsStore(null, api);
    await store.savePreset("props", "Zebra", { a: 1 });
    await store.savePreset("props", "apple", { a: 2 });
    assert.deepEqual(
      store.presets("props").map((p) => p.name),
      ["apple", "Zebra"],
    );
    await store.savePreset("props", "Apple", { a: 3 });
    assert.equal(store.presets("props").length, 2);
    assert.deepEqual(store.presets("props")[0].settings, { a: 3 });
    store.setActivePreset("props", "props:zebra");
    await store.deletePreset("props", "props:zebra");
    assert.deepEqual(calls.deleted, ["props:zebra"]);
    assert.equal(store.presets("props").length, 1);
    assert.equal(store.activePreset("props"), null);
  });

  it("starts with a visible error when the saved settings could not be loaded", () => {
    const store = new SettingsStore(null, fakeApi().api, "could not load");
    assert.equal(store.syncError(), "could not load");
    assert.equal(store.get("props"), undefined);
  });
});

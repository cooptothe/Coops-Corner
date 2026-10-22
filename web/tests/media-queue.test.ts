import { test } from "node:test";
import assert from "node:assert/strict";
import { requestMedia, readMedia } from "../lib/media";
const until = async (check: () => boolean) => {
  const end = Date.now() + 1500;
  while (!check()) {
    if (Date.now() > end) throw Error("Timed out");
    await new Promise((r) => setTimeout(r, 5));
  }
};
test("media lookups deduplicate pending avatars and leave network capacity for feeds", async () => {
  const old = globalThis.fetch;
  let active = 0,
    peak = 0,
    calls = 0;
  const pending: (() => void)[] = [];
  globalThis.fetch = async (input) => {
    calls++;
    active++;
    peak = Math.max(peak, active);
    const u = new URL(String(input), "http://localhost");
    const names = u.searchParams.getAll("n");
    await new Promise<void>((resolve) => pending.push(resolve));
    active--;
    return new Response(
      JSON.stringify({
        results: Object.fromEntries(
          names.map((n) => [n, "/synthetic-headshot.png"]),
        ),
        retry: [],
      }),
    );
  };
  try {
    for (let league = 0; league < 6; league++)
      requestMedia("player", `audit-${league}`, "Player");
    await until(() => calls === 3);
    for (let i = 0; i < 50; i++) requestMedia("player", "audit-0", "Player");
    await new Promise((r) => setTimeout(r, 60));
    assert.equal(calls, 3);
    assert.equal(peak, 3);
    pending.shift()!();
    await until(() => calls === 4);
    assert.equal(peak, 3);
    while (calls < 6 || active) {
      while (pending.length) pending.shift()!();
      await new Promise((r) => setTimeout(r, 5));
    }
    assert.equal(calls, 6);
    assert.equal(
      readMedia("player", "audit-0", "Player"),
      "/synthetic-headshot.png",
    );
  } finally {
    while (pending.length) pending.shift()!();
    globalThis.fetch = old;
  }
});

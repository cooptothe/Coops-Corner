import { test } from "node:test";
import assert from "node:assert/strict";
import { allPages } from "../lib/api";
import { sport } from "../../frontend/format.mjs";

test("middle, arb and EV tools load snapshots larger than 10k in bounded bulk pages", async () => {
  const saved = globalThis.fetch;
  try {
    for (const path of [
      "tools/middle",
      "tools/arbitrage",
      "tools/positive_ev",
    ]) {
      const offsets: number[] = [];
      let active = 0,
        maximum = 0;
      globalThis.fetch = async (url) => {
        const query = new URL(String(url), "http://localhost").searchParams;
        const limit = Number(query.get("limit"));
        const offset = Number(query.get("offset"));
        assert.equal(limit, 1000);
        offsets.push(offset);
        maximum = Math.max(maximum, ++active);
        await new Promise((resolve) => setTimeout(resolve, 1));
        active--;
        const count = Math.min(limit, 12501 - offset);
        return new Response(
          JSON.stringify({
            meta: {
              format: "corner.product_api/1",
              data_mode: "database",
              production_authorized: false,
              availability_verified: false,
              snapshot_id: "bulk",
            },
            data: {
              items: Array.from({ length: count }, (_, i) => offset + i),
              offset,
              limit,
              total: 12501,
              next_offset: offset + count < 12501 ? offset + count : null,
            },
          }),
        );
      };
      const rows = await allPages<number>(
        path,
        "bulk",
        new AbortController().signal,
      );
      assert.equal(rows.length, 12501);
      assert.equal(rows[12500], 12500);
      assert.equal(new Set(rows).size, 12501);
      assert.equal(offsets.length, 13);
      assert.ok(maximum <= 6);
    }
  } finally {
    globalThis.fetch = saved;
  }
});

test("league labels use NFL, NHL and MLB rather than provider IDs", () => {
  assert.equal(sport("americanfootball_nfl"), "NFL");
  assert.equal(sport("icehockey_nhl"), "NHL");
  assert.equal(sport("baseball_mlb"), "MLB");
});

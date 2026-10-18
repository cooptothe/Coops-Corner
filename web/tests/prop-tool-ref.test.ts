import { test } from "node:test";
import assert from "node:assert/strict";
import { quoteRef } from "../lib/slip";
import { MARKETS } from "../../frontend/format.mjs";

test("tracked prop tool legs retain provider event, player, line and prop for CLV", () => {
  const ref = quoteRef({
    game_id: "prop:provider-event",
    contract_id: "exact",
    market_key: "player_threes_alternate",
    selection_name: "Player One Over",
    side: "over",
    point: "2.5",
  });
  assert.equal(ref.game_id, "provider-event");
  assert.equal(ref.market_key, "prop");
  assert.equal(ref.prop_market, "player_threes_alternate");
  assert.equal(ref.player, "Player One");
  assert.equal(ref.point, 2.5);
  assert.equal(MARKETS.player_threes_alternate, "Alternate Made Threes");
  assert.equal(MARKETS.alternate_team_totals, "Alternate team totals");
});

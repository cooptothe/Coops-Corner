import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { DevigSelector } from "../components/devig-comparison";

test("devig methods remain available in the dropdown without comparison buttons", () => {
  const html = renderToStaticMarkup(
    <DevigSelector value="power" onChange={() => {}} />,
  );
  assert.match(html, /DEVIG METHOD/);
  assert.match(html, /value="power" selected/);
  assert.doesNotMatch(html, /Compare devig|<button|<dialog/);
});

import { selectPropDevig } from "../lib/devig-selection";
import type { PropBet } from "../lib/refresh-api";
test("switching a prop method updates fair probability and EV without changing books or stored input", () => {
  const bet = {
    fair_probability: ".5",
    ev: ".1",
    sharps: ["fanduel", "pinnacle"],
    devig_comparisons: [
      { method: "power", probability: ".48", ev: ".056" },
      { method: "worst_case", probability: ".47", ev: ".034" },
    ],
  } as PropBet;
  const selected = selectPropDevig(bet, "power")!;
  assert.equal(selected.fair_probability, ".48");
  assert.equal(selected.ev, ".056");
  assert.equal(selected.sharps, bet.sharps);
  assert.equal(bet.fair_probability, ".5");
  assert.equal(selectPropDevig(bet, "current"), bet);
  assert.equal(selectPropDevig(bet, "shin"), null);
  const modeled = { ...bet, devig_comparisons: null };
  assert.equal(selectPropDevig(modeled, "power"), modeled);
});

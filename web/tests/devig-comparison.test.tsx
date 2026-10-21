import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { DevigComparison } from "../components/devig-comparison";

test("devig comparison stays absent when complete references are unavailable", () => {
  assert.equal(renderToStaticMarkup(<DevigComparison rows={null} />), "");
  assert.equal(renderToStaticMarkup(<DevigComparison rows={[]} />), "");
});
test("comparison is opt-in and does not render a table for every feed row", () => {
  const html = renderToStaticMarkup(
    <DevigComparison
      rows={[{ method: "power", probability: ".5", ev: ".1" }]}
    />,
  );
  assert.match(html, /Compare devig/);
  assert.doesNotMatch(html, /<table|<dialog/);
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

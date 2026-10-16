import test from "node:test";
import assert from "node:assert/strict";
import { renderToStaticMarkup } from "react-dom/server";
import { RangeFilter } from "../components/range-filter";
import { EvFilterLimits } from "../components/ev-filter-limits";

test("unlimited slider has a named endpoint and preserves saved high limits", () => {
  const unlimited = renderToStaticMarkup(
    <RangeFilter
      label="Maximum EV"
      value=""
      onChange={() => {}}
      max={50}
      unlimited
    />,
  );
  assert.match(unlimited, /type="range"/);
  assert.match(unlimited, /aria-valuetext="No limit"/);
  assert.match(unlimited, /value="50.25"/);
  const saved = renderToStaticMarkup(
    <RangeFilter
      label="Maximum EV"
      value="75"
      onChange={() => {}}
      max={50}
      unlimited
    />,
  );
  assert.match(saved, /max="75.25"/);
  assert.match(saved, /value="75"/);
  assert.match(saved, /aria-valuetext="75%"/);
});

test("both limits are labelled sliders with visible values and width guidance", () => {
  const html = renderToStaticMarkup(
    <EvFilterLimits
      maxEv="5"
      maxWidth="20"
      setMaxEv={() => {}}
      setMaxWidth={() => {}}
    />,
  );
  assert.equal((html.match(/type="range"/g) ?? []).length, 2);
  assert.match(html, /aria-valuetext="5%"/);
  assert.match(html, /aria-valuetext="20¢"/);
  assert.match(html, /aria-describedby=/);
});

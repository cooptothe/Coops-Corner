import { test } from "node:test";
import assert from "node:assert/strict";
import { renderToStaticMarkup } from "react-dom/server";
import FreshOdds from "../components/fresh-odds";

test("collection controls fail closed before the server policy is loaded", () => {
  const html = renderToStaticMarkup(<FreshOdds onRefreshed={() => {}} />);
  assert.match(html, /Scheduled collection/);
  assert.doesNotMatch(html, /<button|Refresh odds|API credits|Leagues/);
});

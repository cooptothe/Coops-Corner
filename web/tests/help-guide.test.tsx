import { test } from "node:test";
import assert from "node:assert/strict";
import { renderToStaticMarkup } from "react-dom/server";
import { FeedGuide } from "../components/feed-guide";
import { GUIDES, TOOL_NOTES } from "../lib/help-content";
test("tool guides link to central help without shipping long explanations on the feed", () => {
  for (const view of Object.keys(GUIDES) as (keyof typeof GUIDES)[]) {
    const html = renderToStaticMarkup(<FeedGuide view={view} />);
    assert.match(html, new RegExp("/help#" + view));
    assert.doesNotMatch(html, /<details|<p>/);
  }
  assert.ok(TOOL_NOTES.props.some((text) => text.includes("overround")));
  assert.match(GUIDES.props[1], /FanDuel or Pinnacle/);
});

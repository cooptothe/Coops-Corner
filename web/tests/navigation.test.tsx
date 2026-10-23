import { test } from "node:test";
import assert from "node:assert/strict";
import { renderToStaticMarkup } from "react-dom/server";
import {
  APP_NAVIGATION,
  NavigationLinks,
} from "../components/navigation-links";
import { PersonalNav } from "../components/personal-nav";
test("all signed-in tools share navigation destinations, order and one current page", () => {
  for (const current of ["positive_ev", "props", "lab", "tracker", "account"]) {
    const html = renderToStaticMarkup(<NavigationLinks current={current} />);
    assert.equal((html.match(/aria-current="page"/g) ?? []).length, 1);
    assert.deepEqual(
      [...html.matchAll(/href="([^"]+)"/g)].map((m) => m[1]),
      APP_NAVIGATION.map((x) => "/" + x.id),
    );
    assert.match(html, /Schedule/);
  }
  for (const current of ["lab", "tracker", "account"] as const) {
    const html = renderToStaticMarkup(<PersonalNav current={current} />);
    assert.deepEqual(
      [...html.matchAll(/href="([^"]+)"/g)].map((m) => m[1]),
      APP_NAVIGATION.map((x) => "/" + x.id),
    );
  }
});

import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import {
  BetDisplaySettings,
  screenFeatures,
  screenKey,
  SportsbookLink,
  displayForBook,
  parseDisplayPreferences,
  openDisplayWindow,
} from "../components/bet-display";

const leftDisplay = {
  label: "Left monitor",
  availLeft: -1920,
  availTop: -100,
  availWidth: 1920,
  availHeight: 1080,
};
test("display placement preserves negative monitor coordinates and available bounds", () => {
  assert.equal(
    screenFeatures(leftDisplay),
    "popup=yes,left=-1920,top=-100,width=1920,height=1080,noopener,noreferrer",
  );
  assert.notEqual(
    screenKey(leftDisplay),
    screenKey({ ...leftDisplay, availLeft: 0 }),
  );
});
test("sportsbook links preserve the browser fallback and privacy attributes", () => {
  const html = renderToStaticMarkup(
    <SportsbookLink
      href="https://sportsbook.fanduel.com/"
      target="_blank"
      rel="noopener noreferrer"
      referrerPolicy="no-referrer"
    >
      Bet
    </SportsbookLink>,
  );
  assert.match(html, /target="_blank"/);
  assert.match(html, /rel="noopener noreferrer"/);
  assert.match(html, /referrerPolicy="no-referrer"/);
});
test("display settings render without accessing browser APIs on the server", () => {
  const html = renderToStaticMarkup(<BetDisplaySettings />);
  assert.match(html, /One-click bet display/);
  assert.match(html, /Default browser tab/);
  assert.match(html, /Test default display/);
});

test("per-sportsbook monitors override default and can explicitly use a normal browser tab", () => {
  const prefs = {
    defaultScreen: "monitor-left",
    books: { fanduel: "monitor-right", novig: "" },
  };
  assert.equal(displayForBook(prefs, "FanDuel"), "monitor-right");
  assert.equal(displayForBook(prefs, "fanduel"), "monitor-right");
  assert.equal(displayForBook(prefs, "Novig"), "");
  assert.equal(displayForBook(prefs, "DraftKings"), "monitor-left");
  assert.equal(displayForBook(prefs, "unknown"), "monitor-left");
});
test("malformed saved preferences fall back safely", () => {
  assert.deepEqual(parseDisplayPreferences("broken"), {
    defaultScreen: "",
    books: {},
  });
  assert.deepEqual(
    parseDisplayPreferences(
      '{"defaultScreen":2,"books":{"fanduel":2,"novig":"screen"}}',
    ),
    { defaultScreen: "", books: { novig: "screen" } },
  );
});
test("blocked or throwing popup APIs keep the anchor fallback", () => {
  assert.equal(
    openDisplayWindow("https://sportsbook.fanduel.com/", leftDisplay, {
      open: () => null,
    }),
    false,
  );
  assert.equal(
    openDisplayWindow("https://sportsbook.fanduel.com/", leftDisplay, {
      open: () => {
        throw new Error("blocked");
      },
    }),
    false,
  );
});
test("sportsbook navigation detaches the opener and suppresses referrer before handoff", () => {
  const calls: string[] = [];
  let opener: unknown = {};
  const popup = {
    set opener(value: unknown) {
      opener = value;
      calls.push("detach");
    },
    document: {
      createElement: () => ({}),
      head: {
        appendChild: (meta: { content: string }) => {
          assert.equal(meta.content, "no-referrer");
          calls.push("privacy");
        },
      },
    },
    location: {
      replace: (url: string) => {
        assert.equal(opener, null);
        assert.equal(url, "https://sportsbook.fanduel.com/");
        calls.push("navigate");
      },
    },
  } as unknown as Window;
  assert.equal(
    openDisplayWindow("https://sportsbook.fanduel.com/", leftDisplay, {
      open: () => popup,
    }),
    true,
  );
  assert.deepEqual(calls, ["detach", "privacy", "navigate"]);
});

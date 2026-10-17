import assert from "node:assert/strict";
import { test } from "node:test";
import { quoteClock } from "../components/quote-age";
test("500 quote-age subscribers share one timer, pause when hidden, and clean up", () => {
  const originalDocument = Object.getOwnPropertyDescriptor(
    globalThis,
    "document",
  );
  const originalSet = globalThis.setInterval,
    originalClear = globalThis.clearInterval;
  let hidden = false,
    active = 0,
    created = 0;
  let visibility: () => void = () => {};
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: {
      get hidden() {
        return hidden;
      },
      addEventListener: (_: string, fn: () => void) => {
        visibility = fn;
      },
      removeEventListener: () => {},
    },
  });
  globalThis.setInterval = ((_fn: unknown, delay: number) => {
    assert.equal(delay, 15000);
    created++;
    active++;
    return 123;
  }) as typeof setInterval;
  globalThis.clearInterval = (() => {
    active--;
  }) as typeof clearInterval;
  try {
    const stops = Array.from({ length: 500 }, () =>
      quoteClock.subscribe(() => {}),
    );
    assert.equal(created, 1);
    assert.equal(active, 1);
    assert.ok(quoteClock.getSnapshot() > 0);
    hidden = true;
    visibility();
    assert.equal(active, 0);
    hidden = false;
    visibility();
    assert.equal(active, 1);
    stops.forEach((stop) => stop());
    assert.equal(active, 0);
  } finally {
    globalThis.setInterval = originalSet;
    globalThis.clearInterval = originalClear;
    if (originalDocument)
      Object.defineProperty(globalThis, "document", originalDocument);
    else Reflect.deleteProperty(globalThis, "document");
  }
});

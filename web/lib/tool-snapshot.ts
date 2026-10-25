import { ApiError, allPages } from "./api.ts";
import { subscribeStorageOwner } from "./user-storage.ts";
import type { Page, Quote, ToolRow } from "./contracts.ts";
type Kind = "positive_ev" | "arbitrage" | "middle";
type Bundle = { rows: ToolRow[]; quotes: Quote[] };
type Entry = {
  promise: Promise<Bundle>;
  first?: Bundle;
  listeners: Set<(bundle: Bundle) => void>;
};
const pending = new Map<string, Entry>();
subscribeStorageOwner(() => pending.clear());

export function loadToolSnapshot(
  kind: Kind,
  snapshot: string,
  signal: AbortSignal,
  options: {
    params?: Record<string, string>;
    onFirstPage?: (bundle: Bundle) => void;
  } = {},
): Promise<Bundle> {
  const key = JSON.stringify([
    kind,
    snapshot,
    Object.entries(options.params ?? {}).sort(),
  ]);
  let entry = pending.get(key);
  if (!entry) {
    const current: Entry = { promise: null!, listeners: new Set() };
    const quotes = new Map<string, Quote>();
    current.promise = allPages<ToolRow>(
      `tools/${kind}`,
      snapshot,
      new AbortController().signal,
      {
        limit: 250,
        maxOffset: 100000,
        params: { ...options.params, include_quotes: "true" },
        onPage(page) {
          const typed = page as Page<ToolRow> & { quotes?: Quote[] };
          if (!Array.isArray(typed.quotes))
            throw new ApiError(
              "Feed response is missing its quotes.",
              "invalid_response",
            );
          for (const quote of typed.quotes) {
            if (!quote || typeof quote.id !== "string")
              throw new ApiError("Invalid feed quote.", "invalid_response");
            quotes.set(quote.id, quote);
          }
          if (
            typed.items.some((row) =>
              row.quote_ids.some((id) => !quotes.has(id)),
            )
          )
            throw new ApiError(
              "Feed response has incomplete quotes.",
              "invalid_response",
            );
          if (typed.offset === 0) {
            current.first = {
              rows: typed.items.slice(),
              quotes: typed.quotes.slice(),
            };
            for (const listener of current.listeners) listener(current.first);
          }
        },
      },
    ).then((rows) => ({ rows, quotes: [...quotes.values()] }));
    entry = current;
    pending.set(key, current);
    current.promise.catch(() => {
      if (pending.get(key) === current) pending.delete(key);
    });
    while (pending.size > 4) pending.delete(pending.keys().next().value!);
  }
  const current = entry;
  return new Promise((resolve, reject) => {
    const listener = options.onFirstPage;
    const clean = () => {
      signal.removeEventListener("abort", cancel);
      if (listener) current.listeners.delete(listener);
    };
    const cancel = () => {
      clean();
      reject(new DOMException("Request cancelled", "AbortError"));
    };
    if (signal.aborted) return cancel();
    if (listener) {
      current.listeners.add(listener);
      if (current.first) listener(current.first);
    }
    signal.addEventListener("abort", cancel, { once: true });
    current.promise.then(
      (bundle) => {
        clean();
        resolve({ rows: bundle.rows.slice(), quotes: bundle.quotes.slice() });
      },
      (error) => {
        clean();
        reject(error);
      },
    );
  });
}

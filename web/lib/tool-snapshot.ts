import { ApiError, allPages } from "./api.ts";
import { subscribeStorageOwner } from "./user-storage.ts";
import type { Page, Quote, ToolRow } from "./contracts.ts";

type Kind = "positive_ev" | "arbitrage" | "middle";
type Bundle = { rows: ToolRow[]; quotes: Quote[] };
const pending = new Map<string, Promise<Bundle>>();
subscribeStorageOwner(() => pending.clear());

// Feed pages carry only their referenced quotes. Do not download the entire
// main/alternate/player-prop inventory just to display a few opportunities.
export function loadToolSnapshot(
  kind: Kind,
  snapshot: string,
  signal: AbortSignal,
  options: { params?: Record<string, string> } = {},
): Promise<Bundle> {
  const key = JSON.stringify([
    kind,
    snapshot,
    Object.entries(options.params ?? {}).sort(),
  ]);
  let work = pending.get(key);
  if (!work) {
    const quotes = new Map<string, Quote>();
    work = allPages<ToolRow>(
      `tools/${kind}`,
      snapshot,
      new AbortController().signal,
      {
        limit: 250,
        maxOffset: 100000,
        params: { ...options.params, include_quotes: "true" },
        onPage(page) {
          const related = (page as Page<ToolRow> & { quotes?: Quote[] }).quotes;
          if (!Array.isArray(related))
            throw new ApiError(
              "Feed response is missing its quotes.",
              "invalid_response",
            );
          for (const quote of related) {
            if (!quote || typeof quote.id !== "string")
              throw new ApiError("Invalid feed quote.", "invalid_response");
            quotes.set(quote.id, quote);
          }
        },
      },
    ).then((rows) => {
      if (rows.some((row) => row.quote_ids.some((id) => !quotes.has(id))))
        throw new ApiError(
          "Feed response has incomplete quotes.",
          "invalid_response",
        );
      return { rows, quotes: [...quotes.values()] };
    });
    pending.set(key, work);
    const current = work;
    work.catch(() => {
      if (pending.get(key) === current) pending.delete(key);
    });
    while (pending.size > 4) pending.delete(pending.keys().next().value!);
  }
  return new Promise((resolve, reject) => {
    const cancel = () =>
      reject(new DOMException("Request cancelled", "AbortError"));
    if (signal.aborted) return cancel();
    signal.addEventListener("abort", cancel, { once: true });
    work!.then(
      (bundle) => {
        signal.removeEventListener("abort", cancel);
        resolve({ rows: bundle.rows.slice(), quotes: bundle.quotes.slice() });
      },
      (error) => {
        signal.removeEventListener("abort", cancel);
        reject(error);
      },
    );
  });
}

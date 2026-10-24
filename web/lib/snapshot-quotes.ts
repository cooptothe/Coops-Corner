import { ApiError, allPages, request, sharedPages } from "./api.ts";
import type { Book, Capabilities, Game, Quote } from "./contracts.ts";

const BULK = { limit: 1000, maxOffset: 100000 };

// Read the same immutable snapshot in bounded partitions when its full quote
// list exceeds the API's offset range. Never truncate rows or buy provider odds.
export async function loadSnapshotQuotes(
  snapshot: string,
  signal: AbortSignal,
  books?: Book[],
  mainLinesOnly = false,
): Promise<Quote[]> {
  const query: Record<string, string> = mainLinesOnly
    ? { main_lines_only: "true" }
    : {};
  let legacy = false;
  try {
    return await sharedPages<Quote>("quotes", snapshot, signal, {
      ...BULK,
      params: query,
    });
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.status === 404) legacy = true;
    else if (error.code !== "page_limit") throw error;
  }
  const games = () => sharedPages<Game>("games", snapshot, signal);
  const forGames = async (book?: string) => {
    const items: Quote[] = [];
    // One partition at a time; each partition already has bounded page fan-out.
    // This avoids hundreds of simultaneous game requests on the legacy route.
    for (const game of await games()) {
      const board = await allPages<Quote>(
        `games/${encodeURIComponent(game.id)}/odds`,
        snapshot,
        signal,
        { params: { ...query, ...(book ? { sportsbook_id: book } : {}) } },
      );
      for (const quote of board) items.push(quote);
    }
    return items;
  };
  if (legacy) return forGames();
  const catalog =
    books ??
    (await request<Capabilities>("capabilities", { snapshot, signal })).data
      .books;
  const keys = [...new Set(catalog.map((book) => book.id))].sort();
  if (!keys.length)
    throw new ApiError(
      "Quote snapshot has no sportsbook catalog.",
      "invalid_response",
    );
  const items: Quote[] = [];
  for (const book of keys) {
    let part: Quote[];
    try {
      part = await sharedPages<Quote>("quotes", snapshot, signal, {
        ...BULK,
        params: { ...query, sportsbook_id: book },
      });
    } catch (error) {
      if (!(error instanceof ApiError) || error.code !== "page_limit")
        throw error;
      // A single book can also exceed the bulk bound: partition it by game.
      part = await forGames(book);
    }
    if (part.some((quote) => quote.sportsbook_id !== book))
      throw new ApiError(
        "Quote partition does not match its sportsbook.",
        "invalid_response",
      );
    for (const quote of part) items.push(quote);
  }
  return items;
}

// Parlay review needs only its selected games, not every quote in the workspace.
export async function loadGameQuotes(
  snapshot: string,
  signal: AbortSignal,
  gameIds: string[],
): Promise<Quote[]> {
  const quotes: Quote[] = [];
  for (const id of new Set(gameIds)) {
    const board = await sharedPages<Quote>("quotes", snapshot, signal, {
      ...BULK,
      params: { game_id: id },
    });
    for (const quote of board) quotes.push(quote);
  }
  return quotes;
}

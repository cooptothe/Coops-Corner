export const MAIN_BOOKS = [
  { id: "draftkings", name: "DraftKings" },
  { id: "fanduel", name: "FanDuel" },
  { id: "espnbet", name: "theScore Bet" },
  { id: "betmgm", name: "BetMGM" },
  { id: "novig", name: "Novig" },
  { id: "betrivers", name: "BetRivers" },
  { id: "pinnacle", name: "Pinnacle" },
  { id: "betfair_ex_uk", name: "Betfair Exchange" },
  { id: "prophetx", name: "ProphetX" },
  { id: "kalshi", name: "Kalshi" },
  { id: "betopenly", name: "BetOpenly" },
  { id: "polymarket", name: "Polymarket" },
  { id: "betonlineag", name: "BetOnline" },
  { id: "williamhill_us", name: "Caesars" },
  { id: "bovada", name: "Bovada" },
];
export const PROP_BOOKS = [...MAIN_BOOKS, { id: "fanatics", name: "Fanatics" }];

export function bookDisplayName(id: string, fallback = id) {
  return PROP_BOOKS.find((book) => book.id === id)?.name ?? fallback;
}

// Keep configured sources selectable before their first usable capture.
export function feedBooks(
  captured: { id: string; name: string }[],
  props = false,
) {
  const books = new Map(
    (props ? PROP_BOOKS : MAIN_BOOKS).map((b) => [b.id, b]),
  );
  for (const book of captured.filter(
    (book) =>
      ![
        "betonline",
        "prizepicks",
        "underdog",
        "pick6",
        "dabble_us_dfs",
      ].includes(book.id.toLowerCase()),
  ))
    books.set(book.id, { ...book, name: bookDisplayName(book.id, book.name) });
  return [...books.values()];
}

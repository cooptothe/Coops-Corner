"use client";
import { memo, useEffect, useMemo, useRef, useState } from "react";
import { american, date, point as signed } from "../../frontend/format.mjs";
import type { Capabilities, Game, Meta, Quote } from "../lib/contracts";
import {
  type Cell,
  GRID_MARKETS,
  type GridMarket,
  type Price,
  bestQuoteId,
  buildBoard,
  movement,
  sidesFor,
} from "../lib/odds-grid";
import { Menu, shortBook } from "./arb-feed";
import { Countdown } from "./middle-feed";

type Data = { caps: Capabilities; games: Game[]; quotes: Quote[]; meta: Meta };
const EMPTY = new Map<string, Cell>();
const SETTINGS_KEY = "corner.odds-settings";
const BOOK_ORDER = [
  "pinnacle",
  "draftkings",
  "fanduel",
  "espnbet",
  "betmgm",
  "betrivers",
  "novig",
];
const bookRank = (id: string) => {
  const i = BOOK_ORDER.indexOf(id);
  return i === -1 ? BOOK_ORDER.length : i;
};

const sideTag = (side: string) =>
  side === "over" ? "O" : side === "under" ? "U" : "";

function text(market: GridMarket, side: string, p: Price) {
  const price = american(String(p.decimal));
  if (market === "h2h" || p.point == null) return { line: "", price };
  if (market === "totals")
    return { line: `${sideTag(side)} ${p.point}`, price };
  return { line: signed(String(p.point)), price };
}

const Half = memo(function Half({
  market,
  side,
  price,
  best,
}: {
  market: GridMarket;
  side: string;
  price: Price | undefined;
  best: boolean;
}) {
  const prev = useRef(price);
  const [flash, setFlash] = useState<"up" | "down" | null>(null);
  useEffect(() => {
    const move = movement(market, side, prev.current, price);
    prev.current = price;
    if (!move) return;
    setFlash(move);
    const timer = setTimeout(() => setFlash(null), 500);
    return () => clearTimeout(timer);
  }, [market, side, price]);
  if (!price) return <div className="odds-half empty">-</div>;
  const t = text(market, side, price);
  return (
    <div
      className={`odds-half ${best ? "best" : ""} ${flash ? `flash-${flash}` : ""}`}
    >
      {t.line && <span className="odds-line">{t.line}</span>}
      <b>{t.price}</b>
    </div>
  );
});

const Row = memo(function Row({
  game,
  market,
  books,
  cells,
}: {
  game: Game;
  market: GridMarket;
  books: string[];
  cells: Map<string, Cell>;
}) {
  const [away, home] = game.name.split(" at ");
  const withDraw =
    market === "h2h" && [...cells.values()].some((c) => c.draw !== undefined);
  const sides = sidesFor(market, withDraw);
  const best = new Map<string, string | null>(
    sides.map((s) => [
      s,
      bestQuoteId(
        market,
        s,
        books.flatMap((b) => cells.get(b)?.[s] ?? []),
      ),
    ]),
  );
  const names: Record<string, string> = {
    away,
    home: home ?? "",
    draw: "Draw",
    over: away,
    under: home ?? "",
  };
  return (
    <tr>
      <th scope="row" className="odds-matchup">
        <div className="odds-teams">
          {["away", ...(withDraw ? ["draw"] : []), "home"].map((s) => (
            <span key={s}>{names[s]}</span>
          ))}
        </div>
        <div className="odds-meta">
          <span>{game.competition}</span>
          <span>{date(game.starts_at).replace(/, \d{4}/, "")}</span>
          <Countdown value={game.starts_at} />
        </div>
      </th>
      {books.map((b) => {
        const cell = cells.get(b);
        return (
          <td key={`${b}|${market}`} className="odds-cell">
            {sides.map((s) => (
              <Half
                key={s}
                market={market}
                side={s}
                price={cell?.[s]}
                best={best.get(s) != null && cell?.[s]?.quoteId === best.get(s)}
              />
            ))}
          </td>
        );
      })}
    </tr>
  );
});

export default function OddsScreen({ data }: { data: Data }) {
  const [market, setMarket] = useState<GridMarket>("spreads");
  const [search, setSearch] = useState("");
  const [offBooks, setOffBooks] = useState<Set<string>>(new Set());
  const [offSports, setOffSports] = useState<Set<string>>(new Set());

  useEffect(() => {
    try {
      const s = JSON.parse(localStorage.getItem(SETTINGS_KEY) ?? "{}");
      if (GRID_MARKETS.some((m) => m.key === s.market)) setMarket(s.market);
      if (Array.isArray(s.offBooks))
        setOffBooks(new Set(s.offBooks.map(String)));
      if (Array.isArray(s.offSports))
        setOffSports(new Set(s.offSports.map(String)));
    } catch {}
  }, []);
  useEffect(() => {
    localStorage.setItem(
      SETTINGS_KEY,
      JSON.stringify({
        market,
        offBooks: [...offBooks],
        offSports: [...offSports],
      }),
    );
  }, [market, offBooks, offSports]);

  const boards = useMemo(
    () => ({
      spreads: buildBoard(data.quotes, "spreads"),
      h2h: buildBoard(data.quotes, "h2h"),
      totals: buildBoard(data.quotes, "totals"),
    }),
    [data],
  );
  const board = boards[market];

  // Pre-game only: drop events that have already started.
  const games = useMemo(() => {
    const now = Date.now();
    const term = search.trim().toLowerCase();
    return data.games
      .filter(
        (g) =>
          new Date(g.starts_at).getTime() > now &&
          !offSports.has(g.sport_key) &&
          (!term ||
            `${g.name} ${g.competition}`.toLowerCase().includes(term)) &&
          (["spreads", "h2h", "totals"] as const).some((m) =>
            boards[m].has(g.id),
          ),
      )
      .sort((a, b) => a.starts_at.localeCompare(b.starts_at));
  }, [data, boards, offSports, search]);

  const allBooks = useMemo(() => {
    const present = new Set<string>();
    for (const q of data.quotes) present.add(q.sportsbook_id);
    return data.caps.books
      .filter((b) => present.has(b.id))
      .sort(
        (a, b) =>
          bookRank(a.id) - bookRank(b.id) || a.name.localeCompare(b.name),
      );
  }, [data]);
  const books = allBooks.filter((b) => !offBooks.has(b.id));
  const bookItems = allBooks.map((b): [string, string] => [
    b.id,
    shortBook(b.name),
  ]);
  const sportItems = useMemo(() => {
    const m = new Map<string, string>();
    for (const g of data.games) m.set(g.sport_key, g.competition);
    return [...m].sort((a, b) => a[1].localeCompare(b[1]));
  }, [data]);
  const bookIds = useMemo(() => books.map((b) => b.id), [data, offBooks]);
  const activeIndex = GRID_MARKETS.findIndex((m) => m.key === market);

  return (
    <section className="odds-screen" aria-label="Odds screen">
      <div className="odds-toolbar">
        <div
          className="odds-tabs"
          role="tablist"
          aria-label="Market"
          style={{ ["--i" as string]: activeIndex }}
        >
          <span className="odds-indicator" aria-hidden="true" />
          {GRID_MARKETS.map((m) => (
            <button
              key={m.key}
              role="tab"
              aria-selected={market === m.key}
              className={market === m.key ? "active" : ""}
              onClick={() => setMarket(m.key)}
            >
              {m.label}
            </button>
          ))}
        </div>
        <Menu
          title="Sportsbooks"
          items={bookItems}
          off={offBooks}
          setOff={setOffBooks}
        />
        <Menu
          title="Leagues"
          items={sportItems}
          off={offSports}
          setOff={setOffSports}
        />
        <input
          className="odds-search"
          type="search"
          maxLength={100}
          placeholder="Search a team or league"
          aria-label="Search events"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <span className="arb-status" role="status">
          <i className="arb-pulse" aria-hidden="true" />
          {games.length} upcoming · prices as of {date(data.meta.captured_at)}
        </span>
      </div>
      {games.length === 0 || books.length === 0 ? (
        <div className="empty-state">
          <h3>No upcoming games</h3>
          <p>
            Re-enable leagues or sportsbooks, clear the search, or press Refresh
            odds to fetch the latest pre-game prices.
          </p>
        </div>
      ) : (
        <div className="odds-scroll">
          <table
            className="odds-table"
            style={{ width: 340 + books.length * 124 }}
          >
            <thead>
              <tr>
                <th scope="col" className="odds-corner">
                  Matchup
                </th>
                {books.map((b) => (
                  <th scope="col" key={b.id}>
                    {shortBook(b.name)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {games.map((g) => (
                <Row
                  key={g.id}
                  game={g}
                  market={market}
                  books={bookIds}
                  cells={board.get(g.id) ?? EMPTY}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="odds-note">
        Green marks the best available price for each side. Prices are the last
        stored snapshot; press Refresh odds for new prices, and re-check at the
        sportsbook.
      </p>
    </section>
  );
}

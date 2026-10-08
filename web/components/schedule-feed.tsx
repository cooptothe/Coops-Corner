"use client";
import { useEffect, useMemo, useState } from "react";
import { american, date, point as signed } from "../../frontend/format.mjs";
import { userStorage } from "../lib/user-storage";
import type { Capabilities, Game, Meta, Quote } from "../lib/contracts";
import { isIndividualSport, splitMatchup } from "../lib/media";
import {
  REFERENCE_BOOKS,
  buildGameLines,
  dayHeading,
  dayKey,
  timeLabel,
  type BestPrice,
  type GameLines,
  type LineMarket,
} from "../lib/schedule";
import { Menu, shortBook } from "./arb-feed";
import { Avatar } from "./media";
import { Countdown } from "./middle-feed";

type Data = { caps: Capabilities; games: Game[]; quotes: Quote[]; meta: Meta };

const SETTINGS_KEY = "corner.schedule-settings";
const FIRST_DAYS = 5;
const MORE_DAYS = 5;
const COLUMNS: { key: LineMarket; label: string }[] = [
  { key: "spreads", label: "Spread" },
  { key: "totals", label: "Total" },
  { key: "h2h", label: "Moneyline" },
];

function linePrefix(market: LineMarket, side: string, p: BestPrice): string {
  if (market === "h2h" || p.point == null) return "";
  if (market === "totals") return `${side === "over" ? "O" : "U"} ${p.point}`;
  return p.point === 0 ? "PK" : signed(String(p.point));
}

function Quote_({
  market,
  side,
  price,
  bookName,
}: {
  market: LineMarket;
  side: string;
  price: BestPrice | undefined;
  bookName: (id: string) => string;
}) {
  if (!price) return <div className="sched-quote empty">—</div>;
  const line = linePrefix(market, side, price);
  return (
    <div
      className="sched-quote"
      title={`Best price: ${bookName(price.bookId)}`}
    >
      {line && <span className="sched-line">{line}</span>}
      <b className="sched-price">{american(String(price.decimal))}</b>
      <small className="sched-book">{bookName(price.bookId)}</small>
    </div>
  );
}

function GameRow({
  game,
  lines,
  today,
  bookName,
}: {
  game: Game;
  lines: GameLines | undefined;
  today: boolean;
  bookName: (id: string) => string;
}) {
  const sides = splitMatchup(game.name);
  const kind = isIndividualSport(game.sport_key) ? "player" : "team";
  const withDraw = Boolean(lines?.h2h?.sides.draw);
  return (
    <div role="row" className="sched-row">
      <div role="cell" className="sched-time">
        <strong>{timeLabel(game.starts_at)}</strong>
        {today && <Countdown value={game.starts_at} />}
      </div>
      <div role="cell" className="sched-match">
        {sides ? (
          <>
            {sides.map((name, i) => (
              <div className="sched-team" key={i}>
                <Avatar
                  kind={kind}
                  name={name}
                  sportKey={game.sport_key}
                  size={28}
                />
                <span className="sched-name">{name}</span>
                <span className="sr-only">{i === 0 ? " at " : ""}</span>
              </div>
            ))}
            {withDraw && (
              <div className="sched-team sched-draw">
                <span className="sched-draw-dot" aria-hidden="true" />
                <span className="sched-name">Draw</span>
              </div>
            )}
          </>
        ) : (
          <div className="sched-team">
            <span className="sched-name">{game.name}</span>
          </div>
        )}
        <small className="sched-league">{game.competition}</small>
      </div>
      {COLUMNS.map(({ key, label }) => {
        const main = lines?.[key];
        const order =
          key === "totals"
            ? ["over", "under"]
            : ["away", "home", ...(withDraw && key === "h2h" ? ["draw"] : [])];
        return (
          <div role="cell" className="sched-odds" key={key}>
            <span className="sched-label">{label}</span>
            {main ? (
              order.map((side) => (
                <Quote_
                  key={side}
                  market={key}
                  side={side}
                  price={main.sides[side]}
                  bookName={bookName}
                />
              ))
            ) : (
              <>
                <div className="sched-quote empty">—</div>
                <div className="sched-quote empty">—</div>
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}

export default function ScheduleFeed({ data }: { data: Data }) {
  const [league, setLeague] = useState("");
  const [search, setSearch] = useState("");
  const [offBooks, setOffBooks] = useState<Set<string>>(
    () => new Set(REFERENCE_BOOKS),
  );
  const [dayCount, setDayCount] = useState(FIRST_DAYS);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    try {
      const s = JSON.parse(userStorage.getItem(SETTINGS_KEY) ?? "{}");
      if (Array.isArray(s.offBooks))
        setOffBooks(new Set(s.offBooks.map(String)));
      if (typeof s.league === "string") setLeague(s.league);
    } catch {}
    setReady(true);
  }, []);
  useEffect(() => {
    if (!ready) return;
    userStorage.setItem(
      SETTINGS_KEY,
      JSON.stringify({ offBooks: [...offBooks], league }),
    );
  }, [ready, offBooks, league]);
  useEffect(() => setDayCount(FIRST_DAYS), [league, search, offBooks]);

  const bookNames = useMemo(
    () => new Map(data.caps.books.map((b) => [b.id, shortBook(b.name)])),
    [data],
  );
  const bookName = (id: string) => bookNames.get(id) ?? id;
  const lines = useMemo(
    () => buildGameLines(data.quotes, (id) => !offBooks.has(id)),
    [data, offBooks],
  );
  const bookItems = useMemo(() => {
    const present = new Set(data.quotes.map((q) => q.sportsbook_id));
    return data.caps.books
      .filter((b) => present.has(b.id))
      .map((b): [string, string] => [b.id, shortBook(b.name)])
      .sort((a, b) => a[1].localeCompare(b[1]));
  }, [data]);

  // Pre-game only; events that have started are not schedule items.
  const upcoming = useMemo(() => {
    const now = Date.now();
    return data.games
      .filter((g) => new Date(g.starts_at).getTime() > now)
      .sort(
        (a, b) =>
          a.starts_at.localeCompare(b.starts_at) ||
          a.competition.localeCompare(b.competition) ||
          a.name.localeCompare(b.name),
      );
  }, [data]);
  const leagues = useMemo(() => {
    const counts = new Map<string, { label: string; n: number }>();
    for (const g of upcoming) {
      const held = counts.get(g.sport_key);
      if (held) held.n += 1;
      else counts.set(g.sport_key, { label: g.competition, n: 1 });
    }
    return [...counts]
      .map(([key, v]) => ({ key, ...v }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [upcoming]);
  const activeLeague = leagues.some((l) => l.key === league) ? league : "";

  const visible = useMemo(() => {
    const term = search.trim().toLowerCase();
    return upcoming.filter(
      (g) =>
        (!activeLeague || g.sport_key === activeLeague) &&
        (!term || `${g.name} ${g.competition}`.toLowerCase().includes(term)),
    );
  }, [upcoming, activeLeague, search]);
  const days = useMemo(() => {
    const groups = new Map<string, Game[]>();
    for (const g of visible) {
      const key = dayKey(g.starts_at);
      const list = groups.get(key);
      if (list) list.push(g);
      else groups.set(key, [g]);
    }
    return [...groups];
  }, [visible]);
  const shownDays = days.slice(0, dayCount);
  const now = Date.now();
  const today = dayKey(now);
  const usable = bookItems.filter(([id]) => !offBooks.has(id)).length;

  return (
    <section className="sched" aria-label="Upcoming games">
      <div className="sched-bar">
        <div className="sched-chips" role="group" aria-label="League">
          <button
            type="button"
            className={!activeLeague ? "active" : ""}
            aria-pressed={!activeLeague}
            onClick={() => setLeague("")}
          >
            All leagues <small>{upcoming.length}</small>
          </button>
          {leagues.map((l) => (
            <button
              type="button"
              key={l.key}
              className={activeLeague === l.key ? "active" : ""}
              aria-pressed={activeLeague === l.key}
              onClick={() => setLeague(l.key)}
            >
              {l.label} <small>{l.n}</small>
            </button>
          ))}
        </div>
        <div className="sched-tools">
          <Menu
            title="Odds from"
            items={bookItems}
            off={offBooks}
            setOff={setOffBooks}
          />
          <input
            className="odds-search"
            type="search"
            maxLength={100}
            placeholder="Search a team or league"
            aria-label="Search games"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <span className="arb-status" role="status">
            <i className="arb-pulse" aria-hidden="true" />
            {visible.length} upcoming · prices as of{" "}
            {date(data.meta.captured_at)}
          </span>
        </div>
      </div>
      {visible.length === 0 ? (
        <div className="empty-state">
          <h3>No upcoming games</h3>
          <p>
            Pick another league, clear the search, or press Refresh odds to
            fetch the latest pre-game schedule.
          </p>
        </div>
      ) : (
        <>
          {usable === 0 && (
            <div role="status" className="arb-alert">
              <strong>No sportsbooks selected</strong>
              <span>
                Choose at least one under “Odds from” to see the best lines.
              </span>
            </div>
          )}
          {shownDays.map(([key, games]) => (
            <section className="sched-day" key={key} aria-label={key}>
              <h2 className="sched-date">
                {dayHeading(key, now)}
                <small>
                  {games.length} {games.length === 1 ? "game" : "games"}
                </small>
              </h2>
              <div role="table" className="sched-table" aria-label={key}>
                <div role="row" className="sched-head">
                  <span role="columnheader">Time</span>
                  <span role="columnheader">Matchup</span>
                  {COLUMNS.map((c) => (
                    <span role="columnheader" key={c.key}>
                      {c.label}
                    </span>
                  ))}
                </div>
                {games.map((g) => (
                  <GameRow
                    key={g.id}
                    game={g}
                    lines={lines.get(g.id)}
                    today={key === today}
                    bookName={bookName}
                  />
                ))}
              </div>
            </section>
          ))}
          {days.length > dayCount && (
            <button
              type="button"
              className="button secondary sched-more"
              onClick={() => setDayCount((n) => n + MORE_DAYS)}
            >
              Show more days ({days.length - dayCount} more)
            </button>
          )}
        </>
      )}
      <p className="odds-note">
        Each line is the main line (the one most sportsbooks quote) with the
        best available price on every side, from the books chosen under “Odds
        from”. Prices are the last stored snapshot; press Refresh odds for new
        prices and re-check at the sportsbook.
      </p>
    </section>
  );
}

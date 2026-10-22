"use client";
import { memo, useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "./auth-provider";
import { MAIN_BOOKS, bookDisplayName } from "../lib/bookmakers";
import {
  liveRows,
  liveAmerican,
  liveRange,
  liveFresh,
  type LiveFeed as Feed,
  type LiveKind,
  type LiveMarket,
  type LiveRow,
} from "../lib/live-feed";
import "../app/live-feed.css";

const labels = {
  active: "▶ Lines open",
  no_active_lines: "Ⅱ No active lines",
  unknown: "? Unknown",
};
const markets: Record<LiveMarket, string> = {
  h2h: "Moneyline",
  spreads: "Spreads",
  totals: "Totals",
};
const human = (value: string) => value.replaceAll("_", " ");
const Flash = memo(function Flash({ price }: { price: number }) {
  const previous = useRef(price);
  const [direction, setDirection] = useState("");
  useEffect(() => {
    if (previous.current === price) return;
    setDirection(price > previous.current ? "live-up" : "live-down");
    previous.current = price;
    const timer = setTimeout(() => setDirection(""), 1400);
    return () => clearTimeout(timer);
  }, [price]);
  return (
    <strong className={`live-price ${direction}`}>{liveAmerican(price)}</strong>
  );
});
const Row = memo(function Row({
  row,
  books,
}: {
  row: LiveRow;
  books: typeof MAIN_BOOKS;
}) {
  const { event, candidate: c } = row;
  const selection =
    c?.selection ?? c?.legs?.map((l) => l.selection).join(" / ") ?? "";
  return (
    <tr className={event.status === "no_active_lines" ? "live-stopped" : ""}>
      <td className="live-frozen">
        <small>{human(event.sport_key)}</small>
        <strong>
          {event.away_team} at {event.home_team}
        </strong>
        <span
          className={`live-status live-status-${event.status}`}
          title="Bookmaker line availability; does not confirm whether play has stopped"
        >
          {labels[event.status]}
        </span>
      </td>
      <td>
        {c ? (
          <>
            <strong>
              {markets[c.market]} {c.line}
            </strong>
            <span>{selection}</span>
            {c.legs?.map((l, i) => (
              <small key={i}>
                {bookDisplayName(l.book)} · {l.selection} {l.line} · $
                {Number(l.stake).toFixed(2)}
              </small>
            ))}
          </>
        ) : (
          <>
            <strong>{markets[row.market]}</strong>
            <span>No eligible candidate</span>
          </>
        )}
      </td>
      <td className="live-metric">
        {c?.kind === "ev" ? (
          <>
            <strong>+{Number(c.ev_percent).toFixed(2)}%</strong>
            <span>{bookDisplayName(c.book ?? "")}</span>
          </>
        ) : c?.kind === "arbitrage" ? (
          <>
            <strong>+${Number(c.profit_per_100).toFixed(2)}</strong>
            <small>per $100 · decisive outcomes</small>
          </>
        ) : c ? (
          <>
            <strong>${Number(c.best_profit_per_100).toFixed(2)}</strong>
            <small>
              best / ${Number(c.worst_profit_per_100).toFixed(2)} worst per $100
            </small>
            <span>Window {c.window?.map((w) => w.join("–")).join(", ")}</span>
          </>
        ) : (
          "—"
        )}
      </td>
      <td>
        {c?.fair_probability ? (
          <>
            <strong>{liveAmerican(1 / Number(c.fair_probability))}</strong>
            <span>{(Number(c.fair_probability) * 100).toFixed(1)}%</span>
          </>
        ) : (
          "—"
        )}
      </td>
      {books.map((book) => {
        const data = event.books.find((b) => b.book === book.id);
        const market = data?.markets.find(
          (m) =>
            m.key === (c?.market ?? row.market) &&
            (!c ||
              c.kind === "middle" ||
              c.market === "h2h" ||
              m.outcomes.some((o) => o.point === Number(c.line))),
        );
        const outcomes =
          market?.outcomes.filter(
            (o) => !c?.selection || o.name === c.selection,
          ) ?? [];
        return (
          <td key={book.id}>
            {outcomes.length ? (
              outcomes.map((o) => (
                <div className="live-quote" key={`${o.name}:${o.point}`}>
                  <small>
                    {o.name}
                    {o.point !== undefined ? ` ${o.point}` : ""}
                  </small>
                  <Flash price={o.price} />
                </div>
              ))
            ) : (
              <span
                className="live-unavailable"
                title={
                  data?.status === "unknown"
                    ? "Source unavailable or stale"
                    : "No comparable active quote"
                }
              >
                —
              </span>
            )}
          </td>
        );
      })}
    </tr>
  );
});

export function LiveSwitch({
  enabled,
  onChange,
}: {
  enabled: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <div className="live-mode-control">
      <span className={!enabled ? "selected" : ""}>Pregame</span>
      <button
        type="button"
        className="live-mode-switch"
        role="switch"
        aria-label="Live mode · Premium"
        aria-checked={enabled}
        onClick={() => onChange(!enabled)}
      >
        <span />
      </button>
      <span className={enabled ? "selected" : ""}>
        Live <small>Premium</small>
      </span>
    </div>
  );
}
export default function PremiumLiveFeed({ kind }: { kind: LiveKind }) {
  const { user } = useAuth();
  const premium = user?.username.toLowerCase() === "wonya";
  const [feed, setFeed] = useState<Feed | null>(null),
    [error, setError] = useState("");
  const [market, setMarket] = useState<LiveMarket>("h2h"),
    [sport, setSport] = useState(""),
    [status, setStatus] = useState("");
  const [scroll, setScroll] = useState(0),
    [received, setReceived] = useState(0),
    [clock, setClock] = useState(0);
  const viewport = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!premium) return;
    let alive = true;
    let controller: AbortController | null = null;
    const load = async () => {
      if (document.hidden) return;
      controller?.abort();
      const current = new AbortController();
      controller = current;
      const timeout = setTimeout(() => current.abort(), 10000);
      try {
        const response = await fetch("/api/v1/live-stoppages", {
          credentials: "same-origin",
          cache: "no-store",
          signal: current.signal,
        });
        const body = await response.json();
        if (!response.ok)
          throw new Error(body.error || "Live feed unavailable.");
        if (body.format !== "corner.live_odds/1" || !Array.isArray(body.events))
          throw new Error("Unsupported live response.");
        if (alive) {
          setFeed(body);
          setReceived(Date.now());
          setClock(Date.now());
          setError("");
        }
      } catch (e) {
        if (alive) {
          setError(e instanceof Error ? e.message : "Live feed unavailable.");
          setFeed(null);
        }
      } finally {
        clearTimeout(timeout);
      }
    };
    void load();
    const timer = setInterval(() => void load(), 15000),
      tick = setInterval(() => setClock(Date.now()), 1000);
    return () => {
      alive = false;
      controller?.abort();
      clearInterval(timer);
      clearInterval(tick);
    };
  }, [premium]);
  const rows = useMemo(
    () => (feed ? liveRows(feed, kind, market, sport, status) : []),
    [feed, kind, market, sport, status],
  );
  const visible = rows.filter(
    (row) =>
      !row.candidate ||
      (feed && liveFresh(row.candidate, feed.as_of, clock - received)),
  );
  const range = liveRange(scroll, visible.length);
  useEffect(() => {
    viewport.current?.scrollTo({ top: 0 });
    setScroll(0);
  }, [kind, market, sport, status]);
  const sports = useMemo(
    () => [...new Set(feed?.events.map((e) => e.sport_key) ?? [])].sort(),
    [feed],
  );
  if (!premium)
    return (
      <section className="live-premium-gate">
        <h2>Live is a Premium feature</h2>
        <p>
          Premium access is currently limited to wonya. Turn Live off to return
          to your pregame feed.
        </p>
      </section>
    );
  return (
    <section className="live-feed" aria-label="Premium live main lines">
      <div className="live-filterbar">
        <div className="live-market-tabs" role="group" aria-label="Live market">
          {(Object.keys(markets) as LiveMarket[]).map((key) => (
            <button
              className={market === key ? "button" : "button secondary"}
              key={key}
              aria-pressed={market === key}
              onClick={() => setMarket(key)}
            >
              {markets[key]}
            </button>
          ))}
        </div>
        <label>
          League
          <select value={sport} onChange={(e) => setSport(e.target.value)}>
            <option value="">All live leagues</option>
            {sports.map((s) => (
              <option value={s} key={s}>
                {human(s)}
              </option>
            ))}
          </select>
        </label>
        <div
          className="live-status-tabs"
          role="group"
          aria-label="Line availability"
        >
          {[
            ["", "All"],
            ["active", "▶ Open"],
            ["no_active_lines", "Ⅱ Stopped"],
          ].map(([value, label]) => (
            <button
              key={value}
              className={status === value ? "button" : "button secondary"}
              aria-pressed={status === value}
              title={
                value === "no_active_lines"
                  ? "No active bookmaker lines; not a confirmed game stoppage"
                  : undefined
              }
              onClick={() => setStatus(value)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <p className="live-summary" role="status">
        {error ||
          (!feed
            ? "Loading live snapshots…"
            : !feed.enabled
              ? "Live collection is not enabled yet."
              : `${visible.length} rows · ${human(feed.state)} · odds refresh every minute`)}
      </p>
      <details className="live-explainer">
        <summary>About live status and pricing</summary>
        <p>
          ▶ means lines are open. Ⅱ means no active lines were found in fresh
          captures. ? means status is unknown. These are market signals, not
          confirmation that play has stopped. Source timestamps must be within
          10 seconds across compared books, but identical game state and
          settlement rules remain unverified. Quotes expire after 90 seconds of
          source age. Arbitrage can disappear before both bets are accepted;
          middles show best and worst outcomes, not an estimated win
          probability.
        </p>
        <p>
          Viewing this feed makes no paid odds requests. Live spending:{" "}
          {(feed?.live_credits_accounted ?? 0).toLocaleString()} /{" "}
          {(feed?.monthly_subcap ?? 500000).toLocaleString()} credits inside the
          existing main-market allocation.
        </p>
      </details>
      {feed && visible.length === 0 ? (
        <div className="empty-state">
          <h3>No matching live rows</h3>
          <p>
            Try another market or availability filter. Collection operates from
            8 a.m. to midnight Central.
          </p>
        </div>
      ) : (
        visible.length > 0 && (
          <div
            className="live-grid"
            ref={viewport}
            tabIndex={0}
            aria-label="Live odds grid, scroll horizontally for sportsbooks"
            onScroll={(e) => setScroll(e.currentTarget.scrollTop)}
          >
            <table aria-rowcount={visible.length + 1}>
              <thead>
                <tr>
                  <th className="live-frozen">Event / status</th>
                  <th>Selection / stake</th>
                  <th>
                    {kind === "ev"
                      ? "Estimated EV"
                      : kind === "arbitrage"
                        ? "Conditional profit"
                        : "Middle payoff"}
                  </th>
                  <th>Fair odds</th>
                  {MAIN_BOOKS.map((book) => (
                    <th key={book.id}>{book.name}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {range.top > 0 && (
                  <tr aria-hidden="true">
                    <td
                      colSpan={MAIN_BOOKS.length + 4}
                      style={{ height: range.top, padding: 0 }}
                    />
                  </tr>
                )}
                {visible.slice(range.start, range.end).map((row) => (
                  <Row key={row.id} row={row} books={MAIN_BOOKS} />
                ))}
                {range.bottom > 0 && (
                  <tr aria-hidden="true">
                    <td
                      colSpan={MAIN_BOOKS.length + 4}
                      style={{ height: range.bottom, padding: 0 }}
                    />
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )
      )}
    </section>
  );
}

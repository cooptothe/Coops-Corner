"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { labDate, labLeg } from "../lib/lab";
import { useParlay } from "./parlay-builder";
import { PROP_BOOKS } from "../lib/bookmakers";
import { BetLinkButton } from "./bet-link";
import { american } from "../../frontend/format.mjs";
import {
  trendsRequest,
  type TrendContract,
  type TrendReport,
  type TrendSummary,
} from "../lib/trends-api";

const pct = (value: number | null) =>
  value == null ? "Unavailable" : `${(value * 100).toFixed(1)}%`;
const numeric = (value: number | null) =>
  value == null ? "—" : value.toFixed(1);
const marketName = (key: string) =>
  key.replace(/^(player|batter|pitcher)_/, "").replaceAll("_", " ");

const bookName = (key: string) =>
  PROP_BOOKS.find((book) => book.id === key)?.name ?? key;

function Window({ label, result }: { label: string; result: TrendSummary }) {
  return (
    <div className="trend-window">
      <span>{label}</span>
      <strong>{pct(result.hit_rate)}</strong>
      <small>
        {result.wins} hits / {result.wins + result.losses} decisive games ·{" "}
        {result.pushes} pushes
      </small>
      <small>
        Average {numeric(result.mean)} · Median {numeric(result.median)}
      </small>
    </div>
  );
}

function AddToParlay({ contract }: { contract: TrendContract }) {
  const parlay = useParlay();
  const leg = labLeg(contract);
  if (!parlay || !leg) return null;
  const selected = parlay.selected(leg.key);
  const wrongBook = parlay.draft.active && parlay.draft.book !== leg.book;
  return (
    <button
      type="button"
      className="button secondary"
      disabled={wrongBook || Date.parse(leg.startsAt) <= Date.now()}
      onClick={() =>
        parlay.draft.active ? parlay.toggle(leg) : parlay.start()
      }
    >
      {wrongBook
        ? `Choose ${bookName(parlay.draft.book)}`
        : selected
          ? "Remove from parlay"
          : parlay.draft.active
            ? "Add to parlay"
            : "Build a parlay"}
    </button>
  );
}

export function TrendResults({ report }: { report: TrendReport }) {
  const line = Number(report.contract.point);
  const minimum = Math.min(
    0,
    line,
    ...report.games.map((g) => Number(g.value)),
  );
  const maximum = Math.max(
    1,
    line,
    ...report.games.map((g) => Number(g.value)),
  );
  const y = (value: number) =>
    130 - ((value - minimum) / (maximum - minimum)) * 110;
  return (
    <div className="trend-results">
      <header>
        <h3>
          {report.player} · {report.contract.side} {report.contract.point}{" "}
          {marketName(report.contract.market_key)}
        </h3>
        <p>
          {report.contract.away} at {report.contract.home} ·{" "}
          {bookName(report.contract.book)} {american(report.contract.price)}
        </p>
        {report.contract.observed_at && (
          <p className="trk-muted">
            Quote checked {labDate(report.contract.observed_at)}. Confirm the
            current price at the book.
          </p>
        )}
        {report.contract.links && report.contract.starts_at && (
          <BetLinkButton
            links={report.contract.links}
            bookLabel={bookName(report.contract.book)}
            startsAt={report.contract.starts_at}
          />
        )}
        <AddToParlay contract={report.contract} />
      </header>
      <div className="trend-windows">
        {[1, 5, 10].map((n) => (
          <Window
            key={n}
            label={`Last ${n}`}
            result={report.windows[String(n)]}
          />
        ))}
        <Window label="Baseline (up to 30)" result={report.baseline} />
      </div>
      {!!report.games.length && (
        <figure className="trend-chart">
          <svg
            viewBox="0 0 600 160"
            role="img"
            aria-label="Recent game results compared with the current prop line"
          >
            <line
              x1="0"
              x2="600"
              y1={y(line)}
              y2={y(line)}
              stroke="#ff97b2"
              strokeDasharray="5 4"
            />
            {[...report.games].reverse().map((game, i) => {
              const value = Number(game.value);
              const hit =
                report.contract.side === "Over" ? value > line : value < line;
              return (
                <g key={game.id}>
                  <title>{`${labDate(game.date, true)}: ${value}`}</title>
                  <rect
                    x={i * 59 + 8}
                    y={Math.min(y(value), y(0))}
                    width="40"
                    height={Math.max(1, Math.abs(y(value) - y(0)))}
                    fill={
                      value === line ? "#a998a2" : hit ? "#58ca9a" : "#d9788b"
                    }
                  />
                  <text
                    x={i * 59 + 28}
                    y="153"
                    textAnchor="middle"
                    fill="currentColor"
                    fontSize="10"
                  >
                    {labDate(game.date, true)}
                  </text>
                </g>
              );
            })}
          </svg>
          <figcaption>
            Current line shown in pink. Hits are retrospective at today&apos;s
            line, not the line offered in those games.
          </figcaption>
        </figure>
      )}
      {!report.games.length && (
        <p role="status">
          No usable regular-season game logs were available. Missing data is not
          a zero.
        </p>
      )}
      <div className="trend-context">
        <Window
          label="Previous games vs this opponent"
          result={report.matchup}
        />
        <Window label="Same home/away setting" result={report.venue} />
      </div>
      <details className="trend-model">
        <summary>Model &amp; methodology</summary>
        <h4>
          {report.research_signal ? "Research candidate" : "Research model"}
        </h4>
        <p>
          Smoothed historical estimate{" "}
          <strong>{pct(report.model_probability)}</strong> · Price break-even{" "}
          <strong>{pct(report.break_even_probability)}</strong>
        </p>
        <p>
          Provisional return after modeled fees:{" "}
          <strong>{pct(report.model_ev)}</strong> per unit staked.
        </p>
        <p className="trk-muted">
          This is not calibrated +EV. It does not replace the market-reference
          EV feed. Matchup and news are context, not fitted probability
          adjustments.
        </p>
        {report.workload_change != null && (
          <p>
            Recent workload change: {pct(report.workload_change)} (last five vs
            previous five).
          </p>
        )}
        <ul>
          {report.flags.map((flag) => (
            <li key={flag}>{flag}</li>
          ))}
        </ul>
      </details>
      <details>
        <summary>Game-by-game evidence</summary>
        <div className="trend-table">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Opponent</th>
                <th>Result</th>
                <th>{report.workload_label}</th>
                <th>Season</th>
              </tr>
            </thead>
            <tbody>
              {report.games.map((game) => (
                <tr key={game.id}>
                  <td>
                    {game.source_url ? (
                      <a
                        href={game.source_url}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {labDate(game.date, true)}
                      </a>
                    ) : (
                      labDate(game.date, true)
                    )}
                  </td>
                  <td>{game.opponent}</td>
                  <td>{game.value}</td>
                  <td>{game.workload ?? "—"}</td>
                  <td>{game.season}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
      <details>
        <summary>Historical model check</summary>
        <p>
          {report.historical_replay.held_out_games} chronological holdout games
          · Brier score {numeric(report.historical_replay.brier)} · Log loss{" "}
          {numeric(report.historical_replay.log_loss)}
        </p>
        <p className="trk-muted">
          This replays the current line on past results. It does not use
          archived historical prices or prove betting profitability.
        </p>
      </details>
      <section>
        <h4>Player &amp; matchup news</h4>
        <p>
          <a
            href={report.availability_url}
            target="_blank"
            rel="noopener noreferrer"
          >
            Check the latest injury report
          </a>
        </p>
        {report.news_status !== "available" ? (
          <p>
            News is temporarily unavailable. Check injury and lineup reports
            independently.
          </p>
        ) : report.news.length ? (
          <ul>
            {report.news.map((item) => (
              <li key={item.url}>
                <a href={item.url} target="_blank" rel="noopener noreferrer">
                  {item.headline}
                </a>
                <small> · {labDate(item.published)}</small>
              </li>
            ))}
          </ul>
        ) : (
          <p>
            No matching headlines in the cached source. This does not confirm
            the player is healthy or starting.
          </p>
        )}
      </section>
      <footer className="trk-muted">
        <p>{report.coverage}</p>
        <p>
          {report.source} · Stats checked {labDate(report.stats_fetched_at)}
          {report.news_fetched_at &&
            ` · News checked ${labDate(report.news_fetched_at)}`}
        </p>
      </footer>
    </div>
  );
}

export default function LabResearch({
  selectedBetId,
}: {
  selectedBetId: string | null;
}) {
  const results = useRef<HTMLDivElement>(null);
  const parlay = useParlay();
  const [contracts, setContracts] = useState<TrendContract[]>([]);
  const [selected, setSelected] = useState("");
  const [query, setQuery] = useState("");
  const [sport, setSport] = useState("");
  const [book, setBook] = useState("");
  const [limit, setLimit] = useState(24);
  const [report, setReport] = useState<TrendReport | null>(null);
  useEffect(() => {
    if (report) results.current?.focus({ preventScroll: false });
  }, [report]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [signals, setSignals] = useState<
    { contract: TrendContract; recent?: TrendSummary }[] | null
  >(null);
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState("");
  const legs = useMemo(
    () =>
      contracts
        .map(labLeg)
        .filter((leg): leg is NonNullable<typeof leg> => !!leg),
    [contracts],
  );
  const register = parlay?.register;
  useEffect(() => {
    register?.("lab", legs);
  }, [register, legs]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    trendsRequest<{ contracts: TrendContract[] }>("/options", controller.signal)
      .then((data) => {
        setContracts(data.contracts);
        if (selectedBetId) {
          const match = data.contracts.find((c) => c.bet_id === selectedBetId);
          if (match) setSelected(match.id);
          else
            setError(
              "That quote has expired. Choose another retained prop below.",
            );
        }
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [selectedBetId, retry]);
  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    setBusy(true);
    setReport(null);
    setError("");
    trendsRequest<TrendReport>(
      `?${new URLSearchParams({ id: selected })}`,
      controller.signal,
    )
      .then(setReport)
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setBusy(false);
      });
    return () => controller.abort();
  }, [selected, retry]);
  useEffect(() => {
    if (!scanning) return;
    const controller = new AbortController();
    setScanError("");
    trendsRequest<{
      signals: { contract: TrendContract; recent?: TrendSummary }[];
    }>("/shortlist", controller.signal)
      .then((data) => setSignals(data.signals))
      .catch((e) => {
        if (!controller.signal.aborted) setScanError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setScanning(false);
      });
    return () => controller.abort();
  }, [scanning]);
  const activeBook = parlay?.draft.active ? parlay.draft.book : book;
  const filtered = contracts.filter(
    (c) =>
      (!sport || c.sport_key === sport) &&
      (!activeBook || c.book === activeBook) &&
      `${c.player} ${c.market_label ?? c.market_key} ${c.home} ${c.away} ${bookName(c.book)}`
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  return (
    <section className="lab-research" aria-label="Player research">
      <div className="trend-controls">
        <label className="field">
          <span>Find a player or team</span>
          <input
            type="search"
            value={query}
            placeholder="Search players, teams or markets"
            onChange={(e) => {
              setQuery(e.target.value);
              setLimit(24);
            }}
          />
        </label>
        <label className="field">
          <span>Sport</span>
          <select
            value={sport}
            onChange={(e) => {
              setSport(e.target.value);
              setLimit(24);
            }}
          >
            <option value="">All sports</option>
            {[...new Set(contracts.map((c) => c.sport_key))].map((key) => (
              <option key={key} value={key}>
                {key.split("_").slice(1).join(" ").toUpperCase()}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Sportsbook</span>
          <select
            value={activeBook}
            disabled={!!parlay?.draft.active}
            onChange={(e) => {
              setBook(e.target.value);
              setLimit(24);
            }}
          >
            <option value="">All books</option>
            {[...new Set(contracts.map((c) => c.book))].map((key) => (
              <option key={key} value={key}>
                {bookName(key)}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="lab-discovery">
        <p>
          Choose a prop to see last-game, last-five and last-ten hit rates.
          These describe past results at the current line, not a guaranteed win
          chance.
        </p>
        <button
          className="button secondary"
          type="button"
          disabled={scanning || loading}
          onClick={() => setScanning(true)}
        >
          {scanning ? "Checking research…" : "Find research candidates"}
        </button>
      </div>
      {scanError && <p role="alert">{scanError}</p>}
      {signals && (
        <section className="lab-candidates">
          <h2>Research candidates</h2>
          <p className="trk-muted">
            Based on available cached history; these are research signals, not
            verified +EV bets.
          </p>
          {signals.length ? (
            <div className="lab-selection-grid">
              {signals.map(({ contract: c, recent }) => (
                <button
                  type="button"
                  className="lab-selection"
                  key={c.id}
                  onClick={() => setSelected(c.id)}
                >
                  <strong>{c.player}</strong>
                  <span>
                    {c.side} {c.point}{" "}
                    {c.market_label ?? marketName(c.market_key)}
                  </span>
                  <span>
                    {recent
                      ? `${pct(recent.hit_rate)} · ${recent.wins}/${recent.wins + recent.losses} last 10 decisive games`
                      : "View history"}
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <p>
              No qualifying cached candidates yet. Choose a player below to
              explore available history.
            </p>
          )}
        </section>
      )}
      {loading && <p role="status">Loading available props…</p>}
      {!loading && (
        <>
          <p className="trk-muted">
            {filtered.length} available selections · retained prices · no odds
            credits used
          </p>
          {!filtered.length && (
            <p role="status">
              {contracts.length
                ? "No props match these filters. Try another player, sport or book."
                : "No retained props are available yet. Research will appear when scheduled odds arrive."}
            </p>
          )}
          <div className="lab-selection-grid">
            {filtered.slice(0, limit).map((c) => (
              <button
                type="button"
                key={c.id}
                className="lab-selection"
                aria-pressed={selected === c.id}
                onClick={() => setSelected(c.id)}
              >
                <strong>{c.player}</strong>
                <span>
                  {c.side} {c.point}{" "}
                  {c.market_label ?? marketName(c.market_key)}
                </span>
                <small>
                  {bookName(c.book)} <b>{american(c.price)}</b>
                </small>
                <small>
                  {c.away} at {c.home}
                </small>
                {c.starts_at && (
                  <time dateTime={c.starts_at}>{labDate(c.starts_at)}</time>
                )}
              </button>
            ))}
          </div>
          {filtered.length > limit && (
            <button
              type="button"
              className="button secondary"
              onClick={() => setLimit((n) => n + 24)}
            >
              Show more props
            </button>
          )}
        </>
      )}
      {error && (
        <div role="alert">
          <p>{error}</p>
          <button
            type="button"
            className="button secondary"
            onClick={() => setRetry((n) => n + 1)}
          >
            Try again
          </button>
        </div>
      )}
      {busy && <p role="status">Loading player history and news…</p>}
      {report && !busy && (
        <div
          ref={results}
          tabIndex={-1}
          className="lab-report"
          aria-label="Selected player research"
        >
          <TrendResults report={report} />
        </div>
      )}
    </section>
  );
}

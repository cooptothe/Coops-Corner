"use client";
import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { Avatar } from "./media";
import { LabInsight } from "./lab-insight";
import { LabChart } from "./lab-chart";
import { labDate, labLeg, labDay, labGameId } from "../lib/lab";
import { useParlay } from "./parlay-builder";
import { PROP_BOOKS } from "../lib/bookmakers";
import { BetLinkButton } from "./bet-link";
import { american } from "../../frontend/format.mjs";
import {
  trendsRequest,
  loadTrendOptions,
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

export function TrendResults({
  report,
  quotes,
  onPick,
}: {
  report: TrendReport;
  quotes?: TrendContract[];
  onPick?: (id: string) => void;
}) {
  return (
    <div className="trend-results">
      <header>
        <p>
          Selected offer · {bookName(report.contract.book)}{" "}
          {american(report.contract.price)} · {report.contract.side}{" "}
          {["Over", "Under"].includes(report.contract.side)
            ? report.contract.point
            : ""}
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
      <LabChart
        key={report.contract.id}
        report={report}
        quotes={quotes}
        onPick={onPick}
        renderAction={(quote) => <AddToParlay contract={quote} />}
      />
      <LabInsight report={report} />
      <details className="trend-model">
        <summary>Advanced model details</summary>
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
  const [market, setMarket] = useState("");
  const [browserOpen, setBrowserOpen] = useState(true);
  const [date, setDate] = useState("");
  const [game, setGame] = useState("");
  const deferredQuery = useDeferredValue(query);
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
    loadTrendOptions(controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        setContracts(data.contracts);
        if (selectedBetId) {
          const match = data.contracts.find((c) => c.bet_id === selectedBetId);
          if (match) setSelected(match.id);
          else
            setError(
              "Those odds have expired. Choose another available prop below.",
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
    if (!selected) {
      setBusy(false);
      setReport(null);
      return;
    }
    const controller = new AbortController();
    setBusy(true);
    setReport(null);
    setError("");
    trendsRequest<TrendReport>(
      `?${new URLSearchParams({ id: selected })}`,
      controller.signal,
    )
      .then((value) => {
        if (!controller.signal.aborted) setReport(value);
      })
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
      .then((data) => {
        if (!controller.signal.aborted) setSignals(data.signals);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setScanError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setScanning(false);
      });
    return () => controller.abort();
  }, [scanning]);
  const activeBook = parlay?.draft.active ? parlay.draft.book : book;
  const schedule = useMemo(
    () =>
      [
        ...new Map(
          contracts
            .filter(
              (c) =>
                (!sport || c.sport_key === sport) &&
                (!date || labDay(c.starts_at) === date),
            )
            .map((c) => [labGameId(c), c]),
        ).values(),
      ].sort(
        (a, b) => Date.parse(a.starts_at ?? "") - Date.parse(b.starts_at ?? ""),
      ),
    [contracts, sport, date],
  );
  const activeGame = schedule.some((c) => labGameId(c) === game) ? game : "";
  const filtered = useMemo(
    () =>
      contracts.filter(
        (c) =>
          (!sport || c.sport_key === sport) &&
          (!date || labDay(c.starts_at) === date) &&
          (!activeGame || labGameId(c) === activeGame) &&
          (!market || c.market_key === market) &&
          (!activeBook || c.book === activeBook) &&
          `${c.player} ${c.market_label ?? c.market_key} ${c.home} ${c.away}`
            .toLowerCase()
            .includes(deferredQuery.toLowerCase()),
      ),
    [contracts, sport, date, activeGame, market, activeBook, deferredQuery],
  );
  const players = useMemo(
    () => [
      ...new Map(
        filtered.map((c) => [`${labGameId(c)}:${c.player}`, c]),
      ).values(),
    ],
    [filtered],
  );
  const selectedContract = useMemo(
    () => contracts.find((q) => q.id === selected),
    [contracts, selected],
  );
  const clearSelection = () => {
    setSelected("");
    setReport(null);
    setLimit(24);
  };
  return (
    <section className="lab-research lab-terminal" aria-label="Player research">
      <div className="lab-mobile-toolbar">
        <button
          type="button"
          aria-expanded={browserOpen}
          aria-controls="lab-browser-panel"
          onClick={() => setBrowserOpen((v) => !v)}
        >
          {browserOpen ? "Hide games & players" : "Show games & players"}
        </button>
      </div>
      <div className="lab-master-detail">
        <aside
          id="lab-browser-panel"
          className="lab-browser"
          data-collapsed={!browserOpen}
          aria-label="Games and player filters"
        >
          <div className="lab-browser-heading">
            <h2>Explore props</h2>
            <span>Pregame</span>
          </div>
          <div className="lab-leagues" role="group" aria-label="Sport leagues">
            <button
              type="button"
              aria-pressed={!sport}
              onClick={() => {
                setSport("");
                setGame("");
                setMarket("");
                clearSelection();
              }}
            >
              All
            </button>
            {[...new Set(contracts.map((c) => c.sport_key))].map((key) => (
              <button
                key={key}
                type="button"
                aria-pressed={sport === key}
                onClick={() => {
                  setSport(key);
                  setGame("");
                  setMarket("");
                  clearSelection();
                }}
              >
                {key.split("_").slice(1).join(" ").toUpperCase()}
              </button>
            ))}
          </div>
          <label className="field">
            <span>Game date · Central time</span>
            <input
              type="date"
              value={date}
              onChange={(e) => {
                setDate(e.target.value);
                setGame("");
                clearSelection();
              }}
            />
          </label>
          {date && (
            <button
              type="button"
              className="lab-text-button"
              onClick={() => {
                setDate("");
                setGame("");
                clearSelection();
              }}
            >
              Show all dates
            </button>
          )}
          <details className="lab-schedule" open>
            <summary>
              Games <small>{schedule.length}</small>
            </summary>
            <div className="lab-game-list">
              <button
                type="button"
                aria-pressed={!activeGame}
                onClick={() => {
                  setGame("");
                  clearSelection();
                }}
              >
                All matchups
              </button>
              {schedule.map((c) => (
                <button
                  type="button"
                  key={labGameId(c)}
                  aria-pressed={activeGame === labGameId(c)}
                  onClick={() => {
                    setGame(labGameId(c));
                    clearSelection();
                  }}
                >
                  <strong>
                    {c.away} <span>@</span> {c.home}
                  </strong>
                  <small>
                    {c.starts_at ? labDate(c.starts_at) : "Time unavailable"}
                  </small>
                </button>
              ))}
            </div>
          </details>
          <label className="field">
            <span>Search players or teams</span>
            <input
              type="search"
              value={query}
              placeholder="Player or team"
              onChange={(e) => {
                setQuery(e.target.value);
                setLimit(24);
              }}
            />
          </label>
          <div className="lab-browser-selects">
            <label className="field">
              <span>Stat category</span>
              <select
                value={market}
                onChange={(e) => {
                  setMarket(e.target.value);
                  clearSelection();
                }}
              >
                <option value="">All stats</option>
                {[
                  ...new Map(
                    contracts
                      .filter((c) => !sport || c.sport_key === sport)
                      .map((c) => [
                        c.market_key,
                        c.market_label ?? marketName(c.market_key),
                      ]),
                  ).entries(),
                ].map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
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
                  clearSelection();
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
          <h3 className="lab-list-heading">
            Players <small>{players.length}</small>
          </h3>
          {loading && <p role="status">Loading available props…</p>}
          {!loading && !players.length && (
            <p role="status">
              {contracts.length
                ? "No players match. Change the date, matchup or filters."
                : "No props available yet. Players appear after the next odds update."}
            </p>
          )}
          <div className="lab-selection-grid">
            {players.slice(0, limit).map((c) => (
              <button
                type="button"
                key={`${labGameId(c)}:${c.player}`}
                className="lab-selection"
                aria-pressed={
                  !!selected &&
                  selectedContract?.player === c.player &&
                  selectedContract?.event_id === c.event_id
                }
                onClick={() => setSelected(c.id)}
              >
                <span className="lab-player-choice">
                  <Avatar
                    kind="player"
                    name={c.player}
                    sportKey={c.sport_key}
                    size={34}
                  />
                  <strong>{c.player}</strong>
                </span>
                <small>
                  {c.away} @ {c.home}
                </small>
                <span>
                  {c.market_label ?? marketName(c.market_key)} · {c.side}
                  {["Over", "Under"].includes(c.side) ? ` ${c.point}` : ""}
                </span>
                <small>
                  {bookName(c.book)} <b>{american(c.price)}</b>
                </small>
              </button>
            ))}
          </div>
          {players.length > limit && (
            <button
              className="button secondary"
              type="button"
              onClick={() => setLimit((n) => n + 24)}
            >
              Show more players
            </button>
          )}
          <details className="lab-scan">
            <summary>Explore saved research</summary>
            <button
              type="button"
              className="button secondary"
              disabled={scanning || loading}
              onClick={() => setScanning(true)}
            >
              {scanning ? "Checking…" : "Find players to research"}
            </button>
            {scanError && <p role="alert">{scanError}</p>}
            {signals && (
              <p className="trk-muted">
                {signals.length} cached signals; not validated +EV.
              </p>
            )}
            {signals?.map(({ contract: c }) => (
              <button
                key={c.id}
                className="lab-text-button"
                type="button"
                onClick={() => setSelected(c.id)}
              >
                {c.player} · {c.market_label ?? marketName(c.market_key)}
              </button>
            ))}
          </details>
        </aside>
        <div className="lab-detail">
          {!selected && (
            <div className="lab-detail-placeholder">
              <span className="lab-empty-icon" aria-hidden="true">
                ▥
              </span>
              <h2>Start with a matchup.</h2>
              <p>
                Choose a game, then a player. Compare recent results, test a
                line, and check the context before building your slip.
              </p>
              <small>
                Historical hit rates describe the past. They do not guarantee a
                future result.
              </small>
            </div>
          )}
          {error && (
            <div role="alert" className="lab-error">
              <p>{error}</p>
              <button
                className="button secondary"
                type="button"
                onClick={() => setRetry((n) => n + 1)}
              >
                Try again
              </button>
            </div>
          )}
          {busy && (
            <div className="lab-loading" role="status">
              Loading player history and news…
            </div>
          )}
          {report && !busy && report.contract.id === selected && (
            <div
              ref={results}
              tabIndex={-1}
              className="lab-report"
              aria-label="Selected player research"
            >
              <TrendResults
                report={report}
                quotes={contracts}
                onPick={setSelected}
              />
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  labHistory,
  type HistorySplits,
  type HistoryWindow,
} from "../lib/lab-history";
import { labDate } from "../lib/lab";
import type { TrendContract, TrendReport } from "../lib/trends-api";
import { Avatar } from "./media";
import { american } from "../../frontend/format.mjs";
import { bookDisplayName } from "../lib/bookmakers";

export function LabChart({
  report,
  quotes = [],
  onPick,
  renderAction,
}: {
  report: TrendReport;
  quotes?: TrendContract[];
  onPick?: (id: string) => void;
  renderAction?: (quote: TrendContract) => React.ReactNode;
}) {
  const chartRef = useRef<HTMLElement>(null);
  const [chartWidth, setChartWidth] = useState(640);
  useEffect(() => {
    const element = chartRef.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width;
      if (width) setChartWidth(Math.max(260, Math.round(width)));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [report]);
  const binary = ["Yes", "No"].includes(report.contract.side);
  const quotedSide = (choice: string) =>
    binary && !["Yes", "No"].includes(choice)
      ? choice === "Over"
        ? "Yes"
        : "No"
      : choice;
  const [splits, setSplits] = useState<HistorySplits>({
    venue: "all",
    result: "all",
  });
  const [tooltip, setTooltip] = useState<TrendReport["games"][number] | null>(
    null,
  );
  const hasResults = (report.history_games ?? report.games).some((g) =>
    ["W", "L"].includes(g.game_result ?? ""),
  );
  const statChoices = useMemo(
    () => [
      ...new Map(
        quotes
          .filter(
            (q) =>
              q.event_id === report.contract.event_id &&
              q.player === report.contract.player,
          )
          .map((q) => [q.market_key, q]),
      ).values(),
    ],
    [quotes, report.contract],
  );
  const [window, setWindow] = useState<HistoryWindow>("10");
  const [target, setTarget] = useState(report.contract.point);
  const [side, setSide] = useState<"Over" | "Under">(
    ["Under", "No"].includes(report.contract.side) ? "Under" : "Over",
  );
  const [chart, setChart] = useState<"bar" | "line">("bar");
  const line = Number(target);
  const valid =
    target.trim() !== "" && Number.isFinite(line) && Math.abs(line) < 100000;
  const history = useMemo(
    () =>
      labHistory(
        report,
        window,
        valid ? line : Number(report.contract.point),
        side,
        splits,
      ),
    [report, window, valid, line, side, splits],
  );
  const games = [...history.games].reverse();
  const extent = Math.max(
    1,
    Math.abs(line || 0),
    ...games.map((g) => Math.abs(Number(g.value))),
  );
  const minimum = Math.min(
    0,
    valid ? line : 0,
    ...games.map((g) => Number(g.value)),
  );
  const maximum = Math.max(extent, valid ? line : 0);
  const y = (value: number) =>
    210 - ((value - minimum) / (maximum - minimum)) * 175;
  const x = (i: number) =>
    55 + ((i + 0.5) * (chartWidth - 100)) / Math.max(1, games.length);
  const related = quotes.filter(
    (q) =>
      !!q.event_id &&
      q.event_id === report.contract.event_id &&
      q.player === report.contract.player &&
      q.market_key === report.contract.market_key &&
      valid &&
      Number(q.point) === line,
  );
  const best = (choice: string) =>
    Math.max(
      0,
      ...related
        .filter(
          (q) => q.side === quotedSide(choice) && q.price_kind !== "indicative",
        )
        .map((q) => Number(q.price)),
    );
  const whatIf = valid && line !== Number(report.contract.point);
  return (
    <div className="lab-analysis-grid">
      <section className="lab-analysis" aria-label="Interactive player history">
        <div className="lab-player-profile">
          <Avatar
            kind="player"
            name={report.player}
            sportKey={report.contract.sport_key}
            size={56}
          />
          <div>
            <p className="eyebrow">
              {report.contract.sport_key
                .split("_")
                .slice(1)
                .join(" ")
                .toUpperCase()}{" "}
              · {report.team ?? "PLAYER RESEARCH"}
            </p>
            <h2>{report.player}</h2>
            <p>
              {report.contract.away} at {report.contract.home}
            </p>
            {report.contract.starts_at && (
              <time dateTime={report.contract.starts_at}>
                {labDate(report.contract.starts_at)}
              </time>
            )}
          </div>
          <strong className="lab-stat-label">
            {report.contract.market_label ??
              report.contract.market_key
                .replace(/^(player|batter|pitcher)_/, "")
                .replaceAll("_", " ")}
          </strong>
        </div>
        {statChoices.length > 1 && (
          <div
            className="lab-stat-tabs"
            role="group"
            aria-label="Player stat category"
          >
            {statChoices.map((q) => (
              <button
                type="button"
                key={q.market_key}
                aria-pressed={q.market_key === report.contract.market_key}
                onClick={() => onPick?.(q.id)}
              >
                {q.market_label ?? q.market_key.replaceAll("_", " ")}
              </button>
            ))}
          </div>
        )}
        <div className="lab-chart-controls">
          <div role="group" aria-label="Game history window">
            {(
              [
                ["5", "L5"],
                ["10", "L10"],
                ["20", "L20"],
                ["season", "Season"],
                ["h2h", "H2H"],
              ] as const
            ).map(([value, label]) => (
              <button
                type="button"
                key={value}
                aria-pressed={window === value}
                onClick={() => setWindow(value)}
              >
                {label}
              </button>
            ))}
          </div>
          <div role="group" aria-label="Research side">
            {(["Over", "Under"] as const).map((value) => (
              <button
                key={value}
                type="button"
                aria-pressed={side === value}
                onClick={() => setSide(value)}
              >
                {quotedSide(value)}
              </button>
            ))}
          </div>
          <label className="field">
            <span>Try a line</span>
            <input
              type="number"
              step="0.5"
              disabled={binary}
              value={target}
              onChange={(e) => setTarget(e.target.value)}
            />
          </label>
          {!binary && (
            <label className="field">
              <span>Saved lines</span>
              <select
                aria-label="Saved sportsbook lines"
                value={
                  quotes.some(
                    (q) =>
                      q.event_id === report.contract.event_id &&
                      q.player === report.contract.player &&
                      q.market_key === report.contract.market_key &&
                      q.point === target,
                  )
                    ? target
                    : ""
                }
                onChange={(e) => {
                  if (e.target.value) setTarget(e.target.value);
                }}
              >
                <option value="">Custom line</option>
                {[
                  ...new Set(
                    quotes
                      .filter(
                        (q) =>
                          q.event_id === report.contract.event_id &&
                          q.player === report.contract.player &&
                          q.market_key === report.contract.market_key,
                      )
                      .map((q) => q.point),
                  ),
                ]
                  .sort((a, b) => Number(a) - Number(b))
                  .map((point) => (
                    <option key={point} value={point}>
                      {point}
                    </option>
                  ))}
              </select>
            </label>
          )}
          <label className="field">
            <span>Chart</span>
            <select
              value={chart}
              onChange={(e) => setChart(e.target.value as "bar" | "line")}
            >
              <option value="bar">Bars</option>
              <option value="line">Line</option>
            </select>
          </label>
        </div>
        {!valid && <p role="alert">Enter a valid research line.</p>}
        {whatIf && (
          <p className="lab-what-if">
            What-if research at {target}. This changes historical hit rates
            only; it does not create a sportsbook offer or change your parlay
            leg.
          </p>
        )}
        <div
          className="lc-hit-windows"
          role="group"
          aria-label="Historical hit-rate windows"
        >
          {(["5", "10", "20", "season", "h2h"] as const).map((value) => {
            const result = labHistory(
              report,
              value,
              valid ? line : Number(report.contract.point),
              side,
              splits,
            );
            return (
              <button
                key={value}
                type="button"
                aria-pressed={window === value}
                onClick={() => setWindow(value)}
              >
                <span>
                  {value === "season"
                    ? "SEASON"
                    : value === "h2h"
                      ? "H2H"
                      : `L${value}`}
                </span>
                <strong>
                  {result.hitRate == null
                    ? "—"
                    : `${Math.round(result.hitRate * 100)}%`}
                </strong>
                <small>
                  {result.wins}/{result.decisive}
                  {result.pushes ? ` · ${result.pushes}P` : ""}
                </small>
              </button>
            );
          })}
        </div>
        {!binary && (
          <label className="lc-line-slider">
            <span>
              Research line <strong>{valid ? target : "—"}</strong>
            </span>
            <input
              aria-label="Adjust research threshold"
              type="range"
              min={Math.min(0, minimum)}
              max={Math.ceil(maximum + 5)}
              step="0.5"
              value={valid ? line : 0}
              onChange={(e) => setTarget(e.target.value)}
            />
          </label>
        )}
        <div className="lab-key-metrics">
          <div>
            <small>HIT RATE</small>
            <strong>
              {history.hitRate == null
                ? "—"
                : `${(history.hitRate * 100).toFixed(0)}%`}
            </strong>
            <span>
              {history.wins}/{history.decisive} decisive games ·{" "}
              {history.pushes} pushes
            </span>
          </div>
          <div>
            <small>AVERAGE</small>
            <strong>{history.mean?.toFixed(1) ?? "—"}</strong>
            <span>{history.games.length} available games</span>
          </div>
          <div>
            <small>MEDIAN</small>
            <strong>{history.median?.toFixed(1) ?? "—"}</strong>
            <span>At research line {valid ? target : "—"}</span>
          </div>
        </div>
        {games.length && valid ? (
          <figure ref={chartRef} className="lab-history-chart">
            <div className="lab-chart-scroll">
              <svg
                viewBox={`0 0 ${chartWidth} 270`}
                role="img"
                aria-label={`${window === "h2h" ? "Head-to-head" : window === "season" ? "Available season" : `Last ${window}`} ${side.toLowerCase()} game results against line ${target}`}
              >
                {[0, 0.5, 1].map((f) => {
                  const value = minimum + (maximum - minimum) * f;
                  return (
                    <g key={f}>
                      <line
                        x1="45"
                        x2={chartWidth - 40}
                        y1={y(value)}
                        y2={y(value)}
                        stroke="#44313f"
                      />
                      <text
                        x="35"
                        y={y(value) + 4}
                        textAnchor="end"
                        fill="currentColor"
                        fontSize="11"
                      >
                        {value.toFixed(0)}
                      </text>
                    </g>
                  );
                })}
                {chart === "line" && (
                  <polyline
                    points={games
                      .map((g, i) => `${x(i)},${y(Number(g.value))}`)
                      .join(" ")}
                    fill="none"
                    stroke="#c3a5f5"
                    strokeWidth="3"
                  />
                )}
                {games.map((g, i) => {
                  const value = Number(g.value),
                    hit = side === "Over" ? value > line : value < line;
                  const color =
                    value === line
                      ? "#a1a1aa"
                      : value > line
                        ? "#22c55e"
                        : "#ef4444";
                  return (
                    <g
                      key={g.id}
                      tabIndex={0}
                      onMouseEnter={() => setTooltip(g)}
                      onMouseLeave={() => setTooltip(null)}
                      onClick={() =>
                        setTooltip((old) => (old?.id === g.id ? null : g))
                      }
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          setTooltip(g);
                        }
                      }}
                      onFocus={() => setTooltip(g)}
                      onBlur={() => setTooltip(null)}
                      role="img"
                      aria-label={`${labDate(g.date, true)}, ${g.opponent}, ${value}, ${value === line ? "push" : hit ? "hit" : "miss"}`}
                    >
                      <title>{`${labDate(g.date, true)} vs ${g.opponent}: ${value}; ${report.workload_label}: ${g.workload ?? "unavailable"}`}</title>
                      {chart === "bar" ? (
                        <rect
                          x={
                            x(i) -
                            Math.min(
                              15,
                              ((chartWidth - 100) / games.length) * 0.34,
                            )
                          }
                          y={Math.min(y(value), y(0))}
                          width={Math.min(
                            30,
                            ((chartWidth - 100) / games.length) * 0.68,
                          )}
                          height={Math.max(2, Math.abs(y(value) - y(0)))}
                          rx="3"
                          fill={color}
                        />
                      ) : (
                        <circle cx={x(i)} cy={y(value)} r="5" fill={color} />
                      )}
                      <text
                        x={x(i)}
                        y={Math.max(15, y(value) - 7)}
                        textAnchor="middle"
                        fill="currentColor"
                        fontSize="11"
                      >
                        {games.length <= 20 ? value : ""}
                      </text>
                      {i %
                        Math.max(
                          1,
                          Math.ceil(
                            games.length /
                              Math.max(2, Math.floor((chartWidth - 100) / 60)),
                          ),
                        ) ===
                        0 && (
                        <text
                          x={x(i)}
                          y="235"
                          textAnchor="middle"
                          fill="currentColor"
                          fontSize="10"
                        >
                          {labDate(g.date, true)}
                        </text>
                      )}
                    </g>
                  );
                })}
                <g pointerEvents="none">
                  <line
                    x1="45"
                    x2={chartWidth - 40}
                    y1={y(line)}
                    y2={y(line)}
                    stroke="#ff97b2"
                    strokeDasharray="6 4"
                    strokeWidth="1.5"
                  />
                  <text
                    x={chartWidth - 40}
                    y={y(line) - 8}
                    textAnchor="end"
                    fill="#ffb1bf"
                    fontSize="10"
                  >
                    Line {target}
                  </text>
                </g>
              </svg>
            </div>
            {tooltip && (
              <div className="lab-chart-tooltip" role="status">
                <strong>
                  {labDate(tooltip.date, true)} · {tooltip.opponent}
                </strong>
                <span>
                  {report.contract.market_label ?? "Stat"}: {tooltip.value}
                </span>
                <span>
                  {report.workload_label}: {tooltip.workload ?? "Unavailable"}
                </span>
              </div>
            )}
            <figcaption>
              Green: above line · Red: below line · Gray: push. Results use the
              selected line retrospectively, not the line offered in those
              games. Hover or focus a result for its date and opponent.
            </figcaption>
          </figure>
        ) : (
          <p role="status">
            {window === "h2h"
              ? "No matched opponent history is available."
              : "No usable games in this window."}
          </p>
        )}
        <details className="lab-filtered-log" open>
          <summary>Filtered game log · {history.games.length} games</summary>
          <div className="trend-table">
            <table>
              <thead>
                <tr>
                  <th scope="col">Date</th>
                  <th scope="col">Opponent</th>
                  <th scope="col">Stat</th>
                  <th scope="col">{report.workload_label}</th>
                  <th scope="col">W/L</th>
                </tr>
              </thead>
              <tbody>
                {history.games.map((g) => (
                  <tr key={g.id}>
                    <td>{labDate(g.date, true)}</td>
                    <td>
                      {g.home === true ? "vs " : g.home === false ? "@ " : ""}
                      {g.opponent}
                    </td>
                    <td>{g.value}</td>
                    <td>{g.workload ?? "—"}</td>
                    <td>{g.game_result ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
        <section className="lab-odds-board">
          <h3>Compare sportsbook odds</h3>
          <p className="trk-muted">
            Same player, market and research line. Best listed odds are
            highlighted separately for each side; fees and availability may
            differ.
          </p>
          {related.length ? (
            <div className="lab-offers">
              {related.map((q) => (
                <div
                  key={q.id}
                  className={`lab-offer ${q.price_kind !== "indicative" && Number(q.price) === best(q.side) ? "best" : ""}`}
                >
                  <div>
                    <strong>{bookDisplayName(q.book)}</strong>
                    <span>
                      {q.side}{" "}
                      {["Over", "Under"].includes(q.side) ? q.point : ""} ·{" "}
                      {q.price_kind === "indicative"
                        ? "Indicative price; lineup payout"
                        : american(q.price)}
                    </span>
                    {q.price_kind !== "indicative" &&
                      Number(q.price) === best(q.side) && (
                        <small>Best listed odds</small>
                      )}
                  </div>
                  {onPick && (
                    <button
                      type="button"
                      className="button secondary"
                      onClick={() => onPick(q.id)}
                      disabled={q.id === report.contract.id}
                    >
                      Research
                    </button>
                  )}
                  {renderAction?.(q)}
                </div>
              ))}
            </div>
          ) : (
            <p>
              No saved sportsbook odds at this line. Try the offered line or
              another player.
            </p>
          )}
        </section>
      </section>
      <aside className="lab-splits" aria-label="Contextual splits">
        <h3>Contextual splits</h3>
        <p className="trk-muted">
          Applies instantly to the chart and hit rate.
        </p>
        <fieldset>
          <legend>Venue</legend>
          <div className="lab-split-buttons">
            {(["all", "home", "away"] as const).map((v) => (
              <button
                key={v}
                type="button"
                aria-pressed={splits.venue === v}
                onClick={() => setSplits((x) => ({ ...x, venue: v }))}
              >
                {v === "all" ? "All" : v === "home" ? "Home" : "Away"}
              </button>
            ))}
          </div>
        </fieldset>
        <fieldset>
          <legend>Game result</legend>
          <div className="lab-split-buttons">
            {(["all", "W", "L"] as const).map((v) => (
              <button
                key={v}
                type="button"
                disabled={v !== "all" && !hasResults}
                aria-pressed={splits.result === v}
                onClick={() => setSplits((x) => ({ ...x, result: v }))}
              >
                {v === "all" ? "All" : v === "W" ? "Wins" : "Losses"}
              </button>
            ))}
          </div>
          {!hasResults && <small>Verified game results are unavailable.</small>}
        </fieldset>
        <label className="lab-check">
          <input
            type="checkbox"
            checked={!!splits.h2h}
            disabled={!report.opponent}
            onChange={(e) =>
              setSplits((x) => ({ ...x, h2h: e.target.checked }))
            }
          />
          Head-to-head only
        </label>
        <label className="field">
          <span>Minimum {report.workload_label.toLowerCase()}</span>
          <input
            type="number"
            min="0"
            max="1000"
            value={splits.minWorkload ?? ""}
            placeholder="No minimum"
            onChange={(e) =>
              setSplits((x) => ({
                ...x,
                minWorkload: Math.min(
                  1000,
                  Math.max(0, Number(e.target.value)),
                ),
              }))
            }
          />
        </label>
        <button
          type="button"
          className="button secondary"
          onClick={() => setSplits({ venue: "all", result: "all" })}
        >
          Reset splits
        </button>
        <details>
          <summary>Teammate availability</summary>
          <p>
            With/without splits need verified per-game lineup data, which this
            source does not currently supply.
          </p>
          <button type="button" disabled>
            With / without teammate
          </button>
        </details>
        <section className="lc-splits-table">
          <h4>Split hit rates</h4>
          <table>
            <thead>
              <tr>
                <th>Split</th>
                <th>Hit</th>
                <th>Games</th>
              </tr>
            </thead>
            <tbody>
              {(
                [
                  ["All", {}],
                  ["Home", { venue: "home" }],
                  ["Away", { venue: "away" }],
                  ["H2H", { h2h: true }],
                ] as [string, HistorySplits][]
              ).map(([name, split]) => {
                const result = labHistory(
                  report,
                  window,
                  valid ? line : Number(report.contract.point),
                  side,
                  { ...splits, venue: "all", h2h: false, ...split },
                );
                return (
                  <tr key={name}>
                    <th>{name}</th>
                    <td>
                      {result.hitRate == null
                        ? "—"
                        : `${Math.round(result.hitRate * 100)}%`}
                    </td>
                    <td>{result.games.length}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
        <div className="lab-context-note">
          <h4>Context to check</h4>
          <a
            href={report.availability_url}
            target="_blank"
            rel="noopener noreferrer"
          >
            Injuries &amp; availability ↗
          </a>
          {report.workload_change != null && (
            <p>
              Recent workload: {report.workload_change >= 0 ? "+" : ""}
              {(report.workload_change * 100).toFixed(0)}%
            </p>
          )}
          <p>
            Filtered games are the most recent matching appearances. Season
            includes available logs only, not necessarily every season
            appearance.
          </p>
          <p>
            Historical hit rate is descriptive, not a prediction. Market
            probabilities and parlay prices stay unchanged.
          </p>
        </div>
      </aside>
    </div>
  );
}

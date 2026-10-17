"use client";
import { useMemo, useState } from "react";
import { labHistory, type HistoryWindow } from "../lib/lab-history";
import { labDate } from "../lib/lab";
import type { TrendContract, TrendReport } from "../lib/trends-api";
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
  const binary = ["Yes", "No"].includes(report.contract.side);
  const quotedSide = (choice: string) =>
    binary && !["Yes", "No"].includes(choice)
      ? choice === "Over"
        ? "Yes"
        : "No"
      : choice;
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
      ),
    [report, window, valid, line, side],
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
  const x = (i: number) => 55 + ((i + 0.5) * 700) / Math.max(1, games.length);
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
        .filter((q) => q.side === quotedSide(choice))
        .map((q) => Number(q.price)),
    );
  const whatIf = valid && line !== Number(report.contract.point);
  return (
    <section className="lab-analysis" aria-label="Interactive player history">
      <div className="lab-player-profile">
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
      <div className="lab-chart-controls">
        <div role="group" aria-label="Game history window">
          {(
            [
              ["5", "L5"],
              ["10", "L10"],
              ["20", "L20"],
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
          <span>Research line</span>
          <input
            type="number"
            step="0.5"
            disabled={binary}
            value={target}
            onChange={(e) => setTarget(e.target.value)}
          />
        </label>
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
          What-if research at {target}. This changes historical hit rates only;
          it does not create a sportsbook offer or change your parlay leg.
        </p>
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
            {history.wins}/{history.decisive} decisive games · {history.pushes}{" "}
            pushes
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
        <figure className="lab-history-chart">
          <svg
            viewBox="0 0 800 270"
            role="img"
            aria-label={`${window === "h2h" ? "Head-to-head" : `Last ${window}`} ${side.toLowerCase()} game results against line ${target}`}
          >
            {[0, 0.5, 1].map((f) => {
              const value = minimum + (maximum - minimum) * f;
              return (
                <g key={f}>
                  <line
                    x1="45"
                    x2="760"
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
            <line
              x1="45"
              x2="760"
              y1={y(line)}
              y2={y(line)}
              stroke="#ff97b2"
              strokeDasharray="6 4"
            />
            <text
              x="760"
              y={y(line) - 8}
              textAnchor="end"
              fill="#ffb1bf"
              fontSize="12"
            >
              Line {target}
            </text>
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
                value === line ? "#b6a2b1" : hit ? "#58ca9a" : "#d9788b";
              return (
                <g
                  key={g.id}
                  tabIndex={0}
                  role="img"
                  aria-label={`${labDate(g.date, true)}, ${g.opponent}, ${value}, ${value === line ? "push" : hit ? "hit" : "miss"}`}
                >
                  <title>{`${labDate(g.date, true)} vs ${g.opponent}: ${value}`}</title>
                  {chart === "bar" ? (
                    <rect
                      x={x(i) - Math.min(20, 230 / games.length)}
                      y={Math.min(y(value), y(0))}
                      width={Math.min(40, 460 / games.length)}
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
                    {value}
                  </text>
                  {(games.length <= 10 || i % 2 === 0) && (
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
          </svg>
          <figcaption>
            Green: hit · Rose: miss · Gray: push. Results use the selected line
            retrospectively, not the line offered in those games. Hover or focus
            a result for its date and opponent.
          </figcaption>
        </figure>
      ) : (
        <p role="status">
          {window === "h2h"
            ? "No matched opponent history is available."
            : "No usable games in this window."}
        </p>
      )}
      <section className="lab-odds-board">
        <h3>Compare retained odds</h3>
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
                className={`lab-offer ${Number(q.price) === best(q.side) ? "best" : ""}`}
              >
                <div>
                  <strong>{bookDisplayName(q.book)}</strong>
                  <span>
                    {q.side} {["Over", "Under"].includes(q.side) ? q.point : ""}{" "}
                    · {american(q.price)}
                  </span>
                  {Number(q.price) === best(q.side) && (
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
            No retained sportsbook quotes at this research line. Try the offered
            line or another player.
          </p>
        )}
      </section>
    </section>
  );
}

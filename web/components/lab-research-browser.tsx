"use client";
import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { Avatar } from "./media";
import { american } from "../../frontend/format.mjs";
import { bookDisplayName } from "../lib/bookmakers";
import { labDate, labGameId, labDay } from "../lib/lab";
import { useParlay } from "./parlay-builder";
import { labLeg } from "../lib/lab";
import {
  loadTrendOptions,
  trendsRequest,
  type TrendContract,
  type TrendReport,
} from "../lib/trends-api";
import {
  currentRates,
  reportRates,
  DEFAULT_LAB_FILTERS,
  filterLabBoard,
  labBoardBase,
  validLabOdds,
  type LabFilters,
  type LabRates,
} from "../lib/lab-board";
const label = (c: TrendContract) =>
  c.market_label ??
  c.market_key.replace(/^(player|batter|pitcher)_/, "").replaceAll("_", " ");
export default function LabResearchBrowser({
  selectedBetId,
  renderReport,
}: {
  selectedBetId: string | null;
  renderReport: (
    report: TrendReport,
    quotes: TrendContract[],
    onPick: (id: string) => void,
  ) => React.ReactNode;
}) {
  const [contracts, setContracts] = useState<TrendContract[]>([]);
  const [filters, setFilters] = useState<LabFilters>({
    ...DEFAULT_LAB_FILTERS,
  });
  const search = useDeferredValue(filters.search);
  const [selected, setSelected] = useState("");
  const [report, setReport] = useState<TrendReport | null>(null);
  const [rates, setRates] = useState<Record<string, LabRates>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [warming, setWarming] = useState(false);
  const [error, setError] = useState("");
  const [boardError, setBoardError] = useState("");
  const [retry, setRetry] = useState(0);
  const [page, setPage] = useState(0);
  const detail = useRef<HTMLDivElement>(null);
  const warmAbort = useRef<AbortController | null>(null);
  const parlay = useParlay();
  const register = parlay?.register;
  useEffect(() => () => warmAbort.current?.abort(), []);
  useEffect(() => {
    register?.(
      "lab",
      contracts.map(labLeg).filter((x): x is NonNullable<typeof x> => !!x),
    );
  }, [register, contracts]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    loadTrendOptions(controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        setContracts(data.contracts);
        if (selectedBetId) {
          const found = data.contracts.find((c) => c.bet_id === selectedBetId);
          if (found) setSelected(found.id);
          else
            setError(
              "Those odds have expired. Choose another prop to research.",
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
      .then((data) => {
        if (controller.signal.aborted) return;
        setReport(data);
        setRates((old) => ({ ...old, [data.contract.id]: reportRates(data) }));
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
    if (report) detail.current?.focus({ preventScroll: true });
  }, [report]);
  const viewFilters = useMemo(
    () => ({ ...filters, search }),
    [filters, search],
  );
  const base = useMemo(
    () => labBoardBase(contracts, viewFilters),
    [contracts, viewFilters],
  );
  const rows = useMemo(
    () => filterLabBoard(contracts, viewFilters, rates),
    [contracts, viewFilters, rates],
  );
  const count = Math.max(1, Math.ceil(rows.length / 24));
  const currentPage = Math.min(page, count - 1);
  const visible = rows.slice(currentPage * 24, (currentPage + 1) * 24);
  // With a hit-rate filter, load missing cached summaries in bounded pages even when no rows match yet.
  const cachedIds = (visible.length ? visible : base.slice(0, 24))
    .map((c) => c.id)
    .join(",");
  useEffect(() => {
    if (!cachedIds) return;
    const controller = new AbortController();
    const query = new URLSearchParams();
    for (const id of cachedIds.split(",")) query.append("id", id);
    trendsRequest<{ items: LabRates[] }>(`/board?${query}`, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted)
          setRates((old) => {
            const next = { ...old };
            for (const item of data.items)
              next[item.id] = {
                ...item,
                warm_attempted:
                  item.warm_attempted || old[item.id]?.warm_attempted,
              };
            return next;
          });
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setBoardError(
            "Hit rates are temporarily unavailable. You can still browse props and open player research.",
          );
      });
    return () => controller.abort();
  }, [cachedIds]);
  const update = <K extends keyof LabFilters>(key: K, value: LabFilters[K]) => {
    setFilters((old) => ({
      ...old,
      [key]: value,
      ...(key === "sport" ? { game: "", market: "", team: "" } : {}),
    }));
    setPage(0);
  };
  async function loadRates() {
    warmAbort.current?.abort();
    const controller = new AbortController();
    warmAbort.current = controller;
    setWarming(true);
    setBoardError("");
    const targets = (
      filters.minRate || filters.minGames || filters.sort === "rate"
        ? base.filter((c) => !rates[c.id]?.warm_attempted && currentRates(c, rates[c.id])?.status !== "available").slice(0, 24)
        : visible
    ).filter((c) => currentRates(c, rates[c.id])?.status !== "available");
    if (!targets.length) {
      setBoardError("All matching props on this page have been checked. Some sources may have no game history.");
      setWarming(false);
      return;
    }
    try {
      for (let i = 0; i < targets.length; i += 5) {
        if (controller.signal.aborted) break;
        const query = new URLSearchParams({ warm: "1" });
        for (const c of targets.slice(i, i + 5)) query.append("id", c.id);
        const data = await trendsRequest<{ items: LabRates[] }>(
          `/board?${query}`,
          controller.signal,
        );
        if (!controller.signal.aborted)
          setRates((old) => {
            const next = { ...old };
            for (const item of data.items)
              next[item.id] = {
                ...item,
                warm_attempted:
                  item.warm_attempted || old[item.id]?.warm_attempted,
              };
            return next;
          });
      }
    } catch (e) {
      if (!controller.signal.aborted)
        setBoardError(
          e instanceof Error
            ? e.message
            : "Some history couldn't be loaded. Try opening the player.",
        );
    } finally {
      if (warmAbort.current === controller) setWarming(false);
    }
  }
  const games = [
    ...new Map(
      contracts
        .filter(
          (c) =>
            (!filters.sport || c.sport_key === filters.sport) &&
            (!filters.date || labDay(c.starts_at) === filters.date),
        )
        .map((c) => [labGameId(c), c]),
    ).values(),
  ];
  const select = (
    name: keyof LabFilters,
    title: string,
    options: [string, string][],
  ) => (
    <label className="field">
      <span>{title}</span>
      <select
        value={String(filters[name])}
        onChange={(e) => update(name, e.target.value as never)}
      >
        <option value="">All</option>
        {options.map(([value, text]) => (
          <option key={value} value={value}>
            {text}
          </option>
        ))}
      </select>
    </label>
  );
  return (
    <section
      className="lab-research-board"
      aria-label="All available props research"
    >
      <header className="lab-board-heading">
        <div>
          <p className="eyebrow">GAMES · PLAYERS · PROPS</p>
          <h2>Research the slate</h2>
          <p>
            Browse every available collected prop. No positive-EV requirement.
          </p>
        </div>
        <button
          className="button secondary"
          onClick={() => {
            setFilters({ ...DEFAULT_LAB_FILTERS });
            setPage(0);
          }}
        >
          Reset filters
        </button>
      </header>
      <div className="lab-board-filters">
        {select(
          "sport",
          "League",
          [...new Set(contracts.map((c) => c.sport_key))].map((s) => [
            s,
            s.split("_").slice(1).join(" ").toUpperCase(),
          ]),
        )}
        <label className="field">
          <span>Game date · Central</span>
          <input
            type="date"
            value={filters.date}
            onChange={(e) => {
              update("date", e.target.value);
              update("game", "");
            }}
          />
        </label>
        {select(
          "game",
          "Game",
          games.map((c) => [labGameId(c), `${c.away} @ ${c.home}`]),
        )}
        {select("market", "Prop", [
          ...new Map(
            contracts
              .filter((c) => !filters.sport || c.sport_key === filters.sport)
              .map((c) => [c.market_key, label(c)]),
          ).entries(),
        ])}
        {select(
          "side",
          "Side",
          [...new Set(contracts.map((c) => c.side))].map((s) => [s, s]),
        )}
        {select(
          "book",
          "Sportsbook",
          [...new Set(contracts.map((c) => c.book))].map((s) => [
            s,
            bookDisplayName(s),
          ]),
        )}
        <label className="field lab-board-search">
          <span>Find a player or team</span>
          <input
            type="search"
            placeholder="Player, team or prop"
            value={filters.search}
            onChange={(e) => update("search", e.target.value)}
          />
        </label>
      </div>
      <details className="lab-board-extra">
        <summary>Hit-rate, odds &amp; matchup filters</summary>
        <div className="lab-board-filters">
          <label className="field">
            <span>Hit-rate window</span>
            <select
              value={filters.window}
              onChange={(e) =>
                update("window", e.target.value as LabFilters["window"])
              }
            >
              {[
                ["5", "Last 5"],
                ["10", "Last 10"],
                ["20", "Last 20"],
                ["season", "Season"],
                ["h2h", "Head to head"],
              ].map(([v, t]) => (
                <option value={v} key={v}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Minimum historical hit rate · {filters.minRate}%</span>
            <input
              type="range"
              min="0"
              max="100"
              step="5"
              value={filters.minRate}
              onChange={(e) => update("minRate", Number(e.target.value))}
            />
          </label>
          <label className="field">
            <span>Minimum games in sample</span>
            <input
              type="number"
              min="0"
              max="400"
              value={filters.minGames}
              onChange={(e) =>
                update(
                  "minGames",
                  Math.max(0, Math.min(400, Number(e.target.value))),
                )
              }
            />
          </label>
          {select(
            "team",
            "Team in matchup",
            [...new Set(contracts.flatMap((c) => [c.home, c.away]))]
              .sort()
              .map((t) => [t, t]),
          )}
          <label className="field">
            <span>Minimum American odds</span>
            <input
              inputMode="text"
              placeholder="e.g. -200"
              value={filters.minOdds}
              onChange={(e) => update("minOdds", e.target.value)}
            />
          </label>
          <label className="field">
            <span>Maximum American odds</span>
            <input
              inputMode="text"
              placeholder="e.g. +300"
              value={filters.maxOdds}
              onChange={(e) => update("maxOdds", e.target.value)}
            />
          </label>
        </div>
        <p>
          Hit rates exclude pushes. Missing history stays visible unless you set
          a hit-rate or sample filter. Season uses available current-season
          games.
        </p>
      </details>
      <div className="lab-board-actions">
        <p role="status">
          {loading
            ? "Loading available props…"
            : `${rows.length} props · ${games.length} games`}
        </p>
        <label className="field">
          <span>Sort by</span>
          <select
            value={filters.sort}
            onChange={(e) => update("sort", e.target.value)}
          >
            <option value="time">Game time</option>
            <option value="name">Player name</option>
            <option value="rate">Historical hit rate</option>
          </select>
        </label>
        <button
          className="button secondary"
          disabled={warming || loading || !base.length}
          onClick={loadRates}
        >
          {warming
            ? "Loading game logs…"
            : filters.minRate || filters.minGames || filters.sort === "rate"
              ? "Load more hit rates"
              : "Load hit rates for this page"}
        </button>
        {warming && (
          <button
            className="button secondary"
            onClick={() => {
              warmAbort.current?.abort();
              setWarming(false);
            }}
          >
            Stop loading
          </button>
        )}
      </div>
      <p className="trk-muted">
        Rates use saved game logs. Hit-rate sorting and filters cover loaded
        history only. Loading missing rates uses free research sources, not paid
        odds calls. With all books selected, each row shows the best listed
        price before fees.
      </p>
      {boardError && <p role="status">{boardError}</p>}
      {(!validLabOdds(filters.minOdds) || !validLabOdds(filters.maxOdds)) && (
        <p role="alert">Use American odds such as -110 or +150.</p>
      )}
      {!loading && !rows.length && (
        <p role="status">
          {contracts.length
            ? "No props match these filters. Reset filters or load missing hit rates."
            : "No props have been collected yet. Games and props appear after an odds update."}
        </p>
      )}
      <div className="lab-board-scroll">
        <table className="lab-board-table">
          <caption>Available props and historical hit rates</caption>
          <thead>
            <tr>
              {[
                "Player & prop",
                "Game",
                "Sportsbook / odds",
                "L5",
                "L10",
                "L20",
                "Season",
                "Research",
              ].map((t) => (
                <th key={t} scope="col">
                  {t}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((c) => {
              const history = currentRates(c, rates[c.id]);
              return (
                <tr key={c.id} aria-selected={selected === c.id}>
                  <td>
                    <span className="lab-player-choice">
                      <Avatar
                        kind="player"
                        name={c.player}
                        sportKey={c.sport_key}
                        size={34}
                      />
                      <span>
                        <strong>{c.player}</strong>
                        <small>
                          {label(c)} · {c.side}
                          {["Over", "Under"].includes(c.side)
                            ? ` ${c.point}`
                            : ""}
                        </small>
                      </span>
                    </span>
                  </td>
                  <td>
                    {c.away} @ {c.home}
                    <small>
                      {c.starts_at ? labDate(c.starts_at) : "Time unavailable"}
                    </small>
                  </td>
                  <td>
                    {bookDisplayName(c.book)}
                    <strong>
                      {c.price_kind === "indicative"
                        ? "Indicative / lineup payout"
                        : american(c.price)}
                    </strong>
                  </td>
                  {["5", "10", "20", "season"].map((w) => {
                    const r = history?.windows?.[w];
                    return (
                      <td key={w}>
                        {r?.hit_rate != null ? (
                          <>
                            <strong>{(r.hit_rate * 100).toFixed(0)}%</strong>
                            <small>
                              {r.wins}/{r.wins + r.losses}
                              {r.pushes ? ` · ${r.pushes} pushes` : ""}
                            </small>
                          </>
                        ) : (
                          <span title="Open player research or load missing game logs">
                            —
                          </span>
                        )}
                      </td>
                    );
                  })}
                  <td>
                    <button
                      className="button secondary"
                      onClick={() => {
                        setSelected(c.id);
                        detail.current?.scrollIntoView({
                          behavior: "smooth",
                          block: "start",
                        });
                      }}
                    >
                      {selected === c.id ? "Selected" : "View player"}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {count > 1 && (
        <nav className="lab-board-actions" aria-label="Research board pages">
          <button
            className="button secondary"
            disabled={!currentPage}
            onClick={() => setPage(currentPage - 1)}
          >
            Previous
          </button>
          <span>
            {currentPage + 1} / {count}
          </span>
          <button
            className="button secondary"
            disabled={currentPage >= count - 1}
            onClick={() => setPage(currentPage + 1)}
          >
            Next
          </button>
        </nav>
      )}
      <div
        ref={detail}
        tabIndex={-1}
        className="lab-report"
        aria-label="Selected player research"
      >
        {busy && <p role="status">Loading this player's history and news…</p>}
        {error && (
          <div role="alert">
            <p>{error}</p>
            <button
              className="button secondary"
              onClick={() => setRetry((n) => n + 1)}
            >
              Try again
            </button>
          </div>
        )}
        {report &&
          !busy &&
          report.contract.id === selected &&
          renderReport(report, contracts, setSelected)}
        {!selected && (
          <p className="lab-board-start">
            Choose any prop above to explore its game logs, matchup, news and
            sportsbook lines.
          </p>
        )}
      </div>
    </section>
  );
}

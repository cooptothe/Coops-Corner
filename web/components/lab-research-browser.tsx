"use client";
import {
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Avatar } from "./media";
import { american } from "../../frontend/format.mjs";
import { bookDisplayName } from "../lib/bookmakers";
import {
  labDate,
  labGameId,
  labDay,
  labLeg,
  labQuoteCurrent,
} from "../lib/lab";
import { useParlay } from "./parlay-builder";
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
  type LabFilters,
  type LabRates,
} from "../lib/lab-board";
import {
  labPlayerRows,
  leagueName,
  propLabel,
  virtualRows,
} from "../lib/lab-workspace";

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
  const [inventoryError, setInventoryError] = useState("");
  const [selected, setSelected] = useState("");
  const [reports, setReports] = useState<Record<string, TrendReport>>({});
  const [rates, setRates] = useState<Record<string, LabRates>>({});
  const [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(false),
    [warming, setWarming] = useState(false);
  const [error, setError] = useState(""),
    [boardError, setBoardError] = useState("");
  const [retry, setRetry] = useState(0),
    [scrollTop, setScrollTop] = useState(0);
  const [mobileView, setMobileView] = useState<"players" | "analysis">(
    "players",
  );
  const [showSlate, setShowSlate] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const warmAbort = useRef<AbortController | null>(null);
  const reportCache = useRef<Record<string, TrendReport>>({});
  const report = reports[selected];
  const parlay = useParlay(),
    register = parlay?.register;
  useEffect(() => () => warmAbort.current?.abort(), []);
  useEffect(() => {
    register?.(
      "lab",
      contracts.map(labLeg).filter((x): x is NonNullable<typeof x> => !!x),
    );
  }, [contracts, register]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setInventoryError("");
    loadTrendOptions(controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        const incoming = new Map(data.contracts.map((c) => [c.id, c]));
        const same = (report: TrendReport) => {
          const c = incoming.get(report.contract.id);
          return (
            c &&
            c.price === report.contract.price &&
            c.observed_at === report.contract.observed_at &&
            c.quote_status === report.contract.quote_status
          );
        };
        reportCache.current = Object.fromEntries(
          Object.entries(reportCache.current).filter(([, r]) => same(r)),
        );
        setReports((old) =>
          Object.fromEntries(Object.entries(old).filter(([, r]) => same(r))),
        );
        setContracts(data.contracts);
        const requested = data.contracts.find(
          (c) => c.bet_id === selectedBetId,
        );
        const first =
          requested ??
          data.contracts.find(
            (c) => c.sport_key === "basketball_nba" && labQuoteCurrent(c),
          ) ??
          data.contracts.find((c) => labQuoteCurrent(c)) ??
          data.contracts.find((c) => c.sport_key === "basketball_nba") ??
          data.contracts[0];
        if (first) {
          setFilters((old) => ({
            ...old,
            sport: old.sport || first.sport_key,
            market: old.market || first.market_key,
          }));
          if (requested) {
            setSelected(requested.id);
            setMobileView("analysis");
          }
        }
        if (selectedBetId && !requested)
          setBoardError(
            "That offer has expired. Browse the current slate below.",
          );
      })
      .catch((e) => {
        if (!controller.signal.aborted) setInventoryError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [selectedBetId, retry]);

  useEffect(() => {
    const timer = setInterval(() => {
      if (!document.hidden) setRetry((n) => n + 1);
    }, 60000);
    return () => clearInterval(timer);
  }, []);
  const selectedQuote = contracts.find((c) => c.id === selected);
  const selectedVersion = selectedQuote
    ? JSON.stringify([
        selectedQuote.price,
        selectedQuote.observed_at,
        selectedQuote.quote_status,
      ])
    : "";
  const viewFilters = useMemo(
    () => ({ ...filters, search }),
    [filters, search],
  );
  const base = useMemo(
    () => labPlayerRows(labBoardBase(contracts, viewFilters, true)),
    [contracts, viewFilters],
  );
  const rows = useMemo(
    () => labPlayerRows(filterLabBoard(contracts, viewFilters, rates, true)),
    [contracts, viewFilters, rates],
  );
  const range = virtualRows(rows.length, scrollTop);
  const visible = rows.slice(range.start, range.end);
  const update = <K extends keyof LabFilters>(key: K, value: LabFilters[K]) => {
    setFilters((old) => ({
      ...old,
      [key]: value,
      ...(key === "sport" ? { game: "", market: "", team: "", date: "" } : {}),
      ...(key === "date" ? { game: "" } : {}),
    }));
    setScrollTop(0);
    listRef.current?.scrollTo({ top: 0 });
  };
  // Keep the detail scoped to the current slate/search, even after filter changes.
  useEffect(() => {
    if (!rows.length) {
      setSelected("");
      return;
    }
    const exact = contracts.find((c) => c.id === selected);
    const included = rows.some(
      (c) =>
        c.id === selected ||
        (exact &&
          labGameId(c) === labGameId(exact) &&
          c.player === exact.player &&
          c.market_key === exact.market_key),
    );
    if (!included) setSelected(rows[0].id);
  }, [rows, selected, contracts]);
  useEffect(() => {
    if (!selected) return;
    if (reportCache.current[selected]) {
      setBusy(false);
      return;
    }
    const controller = new AbortController();
    setBusy(true);
    setError("");
    trendsRequest<TrendReport>(
      `?${new URLSearchParams({ id: selected })}`,
      controller.signal,
    )
      .then((data) => {
        if (controller.signal.aborted) return;
        reportCache.current[data.contract.id] = data;
        setReports((old) => ({ ...old, [data.contract.id]: data }));
        setRates((old) => ({ ...old, [data.contract.id]: reportRates(data) }));
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setBusy(false);
      });
    return () => controller.abort();
  }, [selected, retry, selectedVersion]);
  // Fetch cached summaries only for visible rows. No fan-out over the whole slate.
  const visibleIds = visible.map((c) => c.id).join(",");
  useEffect(() => {
    if (!visibleIds) return;
    const controller = new AbortController(),
      query = new URLSearchParams();
    for (const id of visibleIds.split(",")) query.append("id", id);
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
            "Some saved hit rates are unavailable. Open a player to load their history.",
          );
      });
    return () => controller.abort();
  }, [visibleIds]);
  async function loadRates() {
    warmAbort.current?.abort();
    const controller = new AbortController();
    warmAbort.current = controller;
    setWarming(true);
    setBoardError("");
    const targets = (rows.length ? visible : base)
      .filter(
        (c) =>
          !rates[c.id]?.warm_attempted &&
          currentRates(c, rates[c.id])?.status !== "available",
      )
      .slice(0, 24);
    if (!targets.length) {
      setBoardError(
        "Visible players have been checked. Some sources have no matching history.",
      );
      setWarming(false);
      return;
    }
    try {
      for (let i = 0; i < targets.length; i += 4) {
        if (controller.signal.aborted) break;
        const query = new URLSearchParams({ warm: "1" });
        for (const c of targets.slice(i, i + 4)) query.append("id", c.id);
        const data = await trendsRequest<{ items: LabRates[] }>(
          `/board?${query}`,
          controller.signal,
        );
        if (!controller.signal.aborted)
          setRates((old) => ({
            ...old,
            ...Object.fromEntries(
              data.items.map((x) => [x.id, { ...x, warm_attempted: true }]),
            ),
          }));
      }
    } catch (e) {
      if (!controller.signal.aborted)
        setBoardError(
          e instanceof Error
            ? e.message
            : "History is temporarily unavailable.",
        );
    } finally {
      if (warmAbort.current === controller) setWarming(false);
    }
  }
  const games = useMemo(
    () =>
      [
        ...new Map(
          contracts
            .filter(
              (c) =>
                (!filters.sport || c.sport_key === filters.sport) &&
                (!filters.date || labDay(c.starts_at) === filters.date),
            )
            .map((c) => [labGameId(c), c]),
        ).values(),
      ].sort(
        (a, b) => Date.parse(a.starts_at ?? "") - Date.parse(b.starts_at ?? ""),
      ),
    [contracts, filters.sport, filters.date],
  );
  const sports = [...new Set(contracts.map((c) => c.sport_key))];
  const markets = [
    ...new Map(
      contracts
        .filter((c) => !filters.sport || c.sport_key === filters.sport)
        .map((c) => [c.market_key, propLabel(c)]),
    ).entries(),
  ];
  const pick = useCallback(
    (id: string) => {
      const quote = contracts.find((c) => c.id === id);
      if (quote)
        setFilters((old) => ({
          ...old,
          ...(old.market && old.market !== quote.market_key
            ? { market: quote.market_key }
            : {}),
        }));
      setSelected(id);
      setMobileView("analysis");
    },
    [contracts],
  );
  const active = contracts.find((q) => q.id === selected);
  const scrollSlate = (direction: number) =>
    document
      .getElementById("lab-game-slate")
      ?.scrollBy({ left: direction * 320, behavior: "smooth" });
  return (
    <section className="lab-cash" aria-label="Player props research workspace">
      {inventoryError && (
        <div className="lc-alert" role="alert">
          <strong>The game and player list could not load.</strong>
          <p>{inventoryError}</p>
          <button
            className="button secondary"
            onClick={() => setRetry((n) => n + 1)}
          >
            Reload slate
          </button>
        </div>
      )}
      <div className="lc-topbar">
        <div className="lc-pills" role="group" aria-label="Choose sport">
          {sports.map((s) => (
            <button
              key={s}
              aria-pressed={filters.sport === s}
              onClick={() => update("sport", s)}
            >
              {leagueName(s)}
            </button>
          ))}
          {loading && <span>Loading slate…</span>}
        </div>
        <label className="lc-date">
          <span className="sr-only">Game date · Central</span>
          <input
            type="date"
            aria-label="Game date · Central"
            value={filters.date}
            onChange={(e) => update("date", e.target.value)}
          />
        </label>
        <button
          className="lc-reset"
          onClick={() => {
            setFilters({ ...DEFAULT_LAB_FILTERS, sport: filters.sport });
            setScrollTop(0);
            listRef.current?.scrollTo({ top: 0 });
          }}
        >
          Reset
        </button>
      </div>
      <div className="lc-slate-heading">
        <button
          className="lc-slate-toggle"
          aria-expanded={showSlate}
          aria-controls="lab-game-slate"
          onClick={() => setShowSlate(!showSlate)}
        >
          Game slate{" "}
          <span>
            {games.length} games {showSlate ? "−" : "+"}
          </span>
        </button>
        <span className="lc-desktop-label">
          GAME SLATE <small>Times in Central</small>
        </span>
        <div className="lc-slate-arrows">
          <button aria-label="Previous games" onClick={() => scrollSlate(-1)}>
            ‹
          </button>
          <button aria-label="Next games" onClick={() => scrollSlate(1)}>
            ›
          </button>
        </div>
      </div>
      <div
        id="lab-game-slate"
        className={`lc-slate ${showSlate ? "is-open" : ""}`}
        role="group"
        aria-label="Game slate"
      >
        <button
          className="lc-game lc-all-games"
          aria-pressed={!filters.game}
          onClick={() => update("game", "")}
        >
          <strong>All games</strong>
          <span>{games.length} matchups</span>
        </button>
        {games.map((c) => (
          <button
            className="lc-game"
            key={labGameId(c)}
            aria-pressed={filters.game === labGameId(c)}
            onClick={() => update("game", labGameId(c))}
          >
            <span>
              <Avatar
                kind="team"
                sportKey={c.sport_key}
                name={c.away}
                size={18}
              />
              {c.away}
            </span>
            <span>
              <Avatar
                kind="team"
                sportKey={c.sport_key}
                name={c.home}
                size={18}
              />
              {c.home}
            </span>
            <time>{c.starts_at ? labDate(c.starts_at) : "Time pending"}</time>
          </button>
        ))}
      </div>
      <div className="lc-mobile-switch" role="group" aria-label="Research view">
        <button
          aria-pressed={mobileView === "players"}
          onClick={() => setMobileView("players")}
        >
          Players <span>{rows.length}</span>
        </button>
        <button
          aria-pressed={mobileView === "analysis"}
          disabled={!selected}
          onClick={() => setMobileView("analysis")}
        >
          Player analysis
        </button>
      </div>
      <div className="lc-dashboard" data-mobile-view={mobileView}>
        <aside className="lc-master" aria-label="Player and market list">
          <label className="lc-search">
            <span className="sr-only">Search players or teams</span>
            <input
              type="search"
              placeholder="Search player or team"
              value={filters.search}
              onChange={(e) => update("search", e.target.value)}
            />
          </label>
          <div className="lc-market-tabs" role="group" aria-label="Market type">
            <button
              aria-pressed={!filters.market}
              onClick={() => update("market", "")}
            >
              All props
            </button>
            {markets.map(([key, text]) => (
              <button
                key={key}
                aria-pressed={filters.market === key}
                onClick={() => update("market", key)}
              >
                {text}
              </button>
            ))}
          </div>
          <div className="lc-list-tools">
            <label>
              <span className="sr-only">Sort players</span>
              <select
                aria-label="Sort players"
                value={filters.sort}
                onChange={(e) => update("sort", e.target.value)}
              >
                <option value="time">Game time</option>
                <option value="name">Player A–Z</option>
                <option value="rate">Hit rate ↓</option>
              </select>
            </label>
            <label>
              <span className="sr-only">Hit-rate window</span>
              <select
                aria-label="Hit-rate window"
                value={filters.window}
                onChange={(e) =>
                  update("window", e.target.value as LabFilters["window"])
                }
              >
                {[
                  ["5", "L5"],
                  ["10", "L10"],
                  ["20", "L20"],
                  ["season", "Season"],
                  ["h2h", "H2H"],
                ].map(([v, t]) => (
                  <option key={v} value={v}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <details className="lc-list-filters">
            <summary>
              Player filters{" "}
              <small>
                {filters.minRate
                  ? `${filters.minRate}%+ hit rate`
                  : "Side, book & sample"}
              </small>
            </summary>
            <div>
              <label>
                Side
                <select
                  value={filters.side}
                  onChange={(e) => update("side", e.target.value)}
                >
                  <option value="">All sides</option>
                  {[...new Set(contracts.map((c) => c.side))].map((s) => (
                    <option key={s}>{s}</option>
                  ))}
                </select>
              </label>
              <label>
                Sportsbook
                <select
                  value={filters.book}
                  onChange={(e) => update("book", e.target.value)}
                >
                  <option value="">All sportsbooks</option>
                  {[...new Set(contracts.map((c) => c.book))].map((b) => (
                    <option key={b} value={b}>
                      {bookDisplayName(b)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Min. hit rate · {filters.minRate}%
                <input
                  type="range"
                  min="0"
                  max="100"
                  step="5"
                  value={filters.minRate}
                  onChange={(e) => update("minRate", Number(e.target.value))}
                />
              </label>
              <label>
                Min. sample
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
            </div>
          </details>
          <div className="lc-column-labels">
            <span>PLAYER / MARKET</span>
            <span>LINE</span>
            <span>
              {filters.window === "season" ? "SEASON" : `L${filters.window}`}{" "}
              HIT
            </span>
          </div>
          <div
            className="lc-player-scroll"
            ref={listRef}
            onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
            role="list"
            aria-label="Available player props"
            aria-busy={loading}
          >
            <div style={{ height: range.top }} aria-hidden="true" />
            {visible.map((c, index) => {
              const rate = currentRates(c, rates[c.id])?.windows?.[
                filters.window
              ];
              const chosen =
                c.id === selected ||
                (active &&
                  c.player === active.player &&
                  c.market_key === active.market_key &&
                  labGameId(c) === labGameId(active));
              return (
                <div
                  role="listitem"
                  key={c.id}
                  aria-posinset={range.start + index + 1}
                  aria-setsize={rows.length}
                >
                  <button
                    className="lc-player"
                    aria-pressed={!!chosen}
                    onClick={() => pick(c.id)}
                    title={`${c.player} · ${propLabel(c)} · ${c.away} @ ${c.home}`}
                  >
                    <Avatar
                      kind="player"
                      sportKey={c.sport_key}
                      name={c.player}
                      size={28}
                    />
                    <span className="lc-player-name">
                      <strong>{c.player}</strong>
                      <small>
                        <span
                          className="lc-mini-dots"
                          aria-label="Last five games, oldest first"
                        >
                          {(
                            currentRates(c, rates[c.id])?.recent_values ?? []
                          ).map((v, i) => (
                            <i
                              key={i}
                              title={`${v}: ${Number(v) === Number(c.point) ? "push" : (["Over", "Yes"].includes(c.side) ? Number(v) > Number(c.point) : Number(v) < Number(c.point)) ? "hit" : "miss"}`}
                              style={{
                                background:
                                  Number(v) === Number(c.point)
                                    ? "#a1a1aa"
                                    : (
                                          ["Over", "Yes"].includes(c.side)
                                            ? Number(v) > Number(c.point)
                                            : Number(v) < Number(c.point)
                                        )
                                      ? "#22c55e"
                                      : "#ef4444",
                              }}
                            />
                          ))}
                        </span>
                        {propLabel(c)}
                        {!labQuoteCurrent(c) && " · Saved"} · {c.away} @{" "}
                        {c.home}
                      </small>
                    </span>
                    <span className="lc-line">
                      <small>{c.side}</small>
                      <strong>
                        {["Yes", "No"].includes(c.side) ? "—" : c.point}
                      </strong>
                    </span>
                    <span
                      className={`lc-rate ${rate?.hit_rate != null && rate.hit_rate >= 0.7 ? "is-high" : ""}`}
                      title={
                        rate
                          ? `${rate.wins}/${rate.wins + rate.losses} decisive games; ${rate.pushes} pushes`
                          : "History not loaded"
                      }
                    >
                      {rate?.hit_rate != null
                        ? `${Math.round(rate.hit_rate * 100)}%`
                        : "—"}
                    </span>
                  </button>
                </div>
              );
            })}
            <div style={{ height: range.bottom }} aria-hidden="true" />
            {loading && (
              <div className="lc-list-empty" role="status">
                Loading saved props…
              </div>
            )}
            {!loading && !rows.length && (
              <div className="lc-list-empty">
                {inventoryError
                  ? "The slate request failed. Use Reload slate above."
                  : contracts.length
                    ? "No players match. Reset filters or load missing history."
                    : "No research props have been saved yet. Once collected, props remain available here even when their odds expire."}
              </div>
            )}
          </div>
          <footer className="lc-list-footer">
            <span>{rows.length} player props</span>
            <button
              disabled={warming || loading || !base.length}
              onClick={loadRates}
            >
              {warming ? "Loading…" : "Load hit rates"}
            </button>
            {warming && (
              <button
                onClick={() => {
                  warmAbort.current?.abort();
                  setWarming(false);
                }}
              >
                Stop
              </button>
            )}
          </footer>
          <p className="lc-source-note">
            Saved lines remain available for research. Newer collected lines
            update automatically. Missing game history is shown as —.
          </p>
        </aside>
        <div
          className="lc-detail"
          aria-label="Selected player research"
          aria-busy={busy}
        >
          {error && (
            <div role="alert" className="lc-alert">
              <p>{error}</p>
              <button
                className="button secondary"
                onClick={() => setRetry((n) => n + 1)}
              >
                Try again
              </button>
            </div>
          )}
          {busy && (
            <div className="lc-detail-loading" role="status">
              <div className="lc-skeleton" />
              <p>Loading player history & matchup…</p>
              <div className="lc-skeleton lc-skeleton-chart" />
            </div>
          )}
          {!busy && report && renderReport(report, contracts, pick)}
          {!busy && !report && !error && (
            <div className="lc-detail-empty">
              <span>THE LAB</span>
              <h2>Find your angle.</h2>
              <p>
                Choose a player to explore game logs, compare lines and research
                the matchup.
              </p>
            </div>
          )}
        </div>
      </div>
      {boardError && (
        <p className="lc-alert" role="status">
          {boardError}
        </p>
      )}
      <footer className="lc-footnote">
        Research all collected props, independent of +EV. Main line uses the
        widest saved book coverage; alternate lines and exact offers are inside
        player analysis. Sorting by hit rate uses loaded history only.
      </footer>
    </section>
  );
}

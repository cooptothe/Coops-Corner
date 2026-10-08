"use client";
import Image from "next/image";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useReducer, useState } from "react";
import {
  addBets,
  addCash,
  deleteBet,
  deleteCash,
  loadLive,
  loadTracker,
  measureClv,
  reopenBet,
  settleBet,
  updateBet,
  type NewBetBody,
  type NewCashBody,
  type Result,
} from "../lib/tracker-api";
import { importLegacySlip, notifyLogged } from "../lib/slip";
import {
  STRATEGY_LABEL,
  bookBalances,
  bookLabel,
  kpis,
  leagueLabel,
  totals,
} from "../lib/tracker-math";
import {
  EMPTY_FILTERS,
  filtersActive,
  initialView,
  matchesFilters,
  orderBets,
  trackerReducer,
  type Filters,
} from "../lib/tracker-state";
import { BankrollTab } from "./tracker-bankroll";
import {
  BetDrawer,
  BetRow,
  BookList,
  KpiRibbon,
  LogDrawer,
  PickMenu,
} from "./tracker-parts";

const DAY = 86400000;
const LIVE_EVERY = 30000;
const LIVE_LEAD = 20 * 60000;
const PAGE = 100;

type Panel = { kind: "log" } | { kind: "bet"; id: string } | null;
const message = (e: unknown, fallback: string) =>
  e instanceof Error ? e.message : fallback;

export default function Tracker() {
  const [view, dispatch] = useReducer(trackerReducer, initialView);
  const [phase, setPhase] = useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = useState("");
  const [tab, setTab] = useState<"bets" | "bankroll">("bets");
  const [windowDays, setWindowDays] = useState<number | null>(null);
  const [panel, setPanel] = useState<Panel>(null);
  const [notice, setNotice] = useState("");
  const [shown, setShown] = useState(PAGE);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    document.title = "Tracker & bankroll — The Corner";
    const timer = setInterval(() => setNow(Date.now()), 60000);
    return () => clearInterval(timer);
  }, []);

  const load = useCallback(async (quiet: boolean) => {
    try {
      await importLegacySlip();
      const state = await loadTracker();
      dispatch({ type: "LOAD", bets: state.bets, cash: state.cash });
      setPhase("ready");
      const started = Date.now() - 5 * 60000;
      if (
        state.bets.some(
          (b) =>
            !b.clv &&
            b.ref.game_id &&
            b.starts_at &&
            new Date(b.starts_at).getTime() <= started,
        )
      )
        measureClv().then(
          (result) =>
            result.bets.length &&
            dispatch({ type: "BET_UPSERT", bets: result.bets }),
          () => undefined,
        );
    } catch (e) {
      if (!quiet) {
        setLoadError(message(e, "The tracker could not be loaded."));
        setPhase("error");
      }
    }
  }, []);
  useEffect(() => {
    load(false);
    const refocus = () => document.visibilityState === "visible" && load(true);
    document.addEventListener("visibilitychange", refocus);
    return () => document.removeEventListener("visibilitychange", refocus);
  }, [load]);

  // Live progress: poll only while an open bet's game is under way and the tab is visible.
  const pending = useMemo(
    () => view.bets.filter((b) => b.status === "pending"),
    [view.bets],
  );
  const watching = pending.some(
    (b) => b.starts_at && new Date(b.starts_at).getTime() - LIVE_LEAD <= now,
  );
  const watchKey = pending.map((b) => b.id).join(",");
  useEffect(() => {
    if (!watching || phase !== "ready") return;
    let stopped = false;
    const poll = async () => {
      if (document.visibilityState !== "visible") return;
      try {
        const result = await loadLive();
        if (!stopped) dispatch({ type: "LIVE_UPDATE", live: result.live });
      } catch {
        // A missed poll is harmless; the next one retries.
      }
    };
    poll();
    const timer = setInterval(poll, LIVE_EVERY);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [watching, watchKey, phase]);

  const fail = useCallback(
    (e: unknown) => setNotice(message(e, "That did not work.")),
    [],
  );

  const settle = useCallback(
    async (id: string, result: Result, returned?: string) => {
      const saved = await settleBet(
        id,
        result,
        returned ? { returned } : undefined,
      );
      dispatch({ type: "BET_UPSERT", bets: [saved.bet] });
    },
    [],
  );
  const apply = useCallback(
    (id: string, result: Result) => {
      settle(id, result).catch(fail);
    },
    [settle, fail],
  );
  const reopen = useCallback(async (id: string) => {
    const saved = await reopenBet(id);
    dispatch({ type: "BET_UPSERT", bets: [saved.bet] });
  }, []);
  const update = useCallback(
    async (id: string, changes: Record<string, unknown>) => {
      const saved = await updateBet(id, changes);
      dispatch({ type: "BET_UPSERT", bets: [saved.bet] });
    },
    [],
  );
  const remove = useCallback(async (id: string) => {
    await deleteBet(id);
    dispatch({ type: "BET_REMOVE", id });
    setPanel(null);
  }, []);
  const logManual = useCallback(async (items: NewBetBody[]) => {
    const saved = await addBets(items);
    dispatch({ type: "BET_UPSERT", bets: saved.bets });
    notifyLogged();
    setPanel(null);
  }, []);
  const addCashEntry = useCallback(async (body: NewCashBody) => {
    const saved = await addCash(body);
    dispatch({ type: "CASH_UPSERT", cash: saved.cash });
  }, []);
  const removeCash = useCallback(async (id: string) => {
    await deleteCash(id);
    dispatch({ type: "CASH_REMOVE", id });
  }, []);
  const select = useCallback((id: string) => setPanel({ kind: "bet", id }), []);
  const closePanel = useCallback(() => setPanel(null), []);
  const setFilters = useCallback((filters: Partial<Filters>) => {
    dispatch({ type: "SET_FILTER", filters });
    setShown(PAGE);
  }, []);

  const filtered = useMemo(
    () => view.bets.filter((b) => matchesFilters(b, view.filters)),
    [view.bets, view.filters],
  );
  const ordered = useMemo(() => orderBets(filtered), [filtered]);
  const balances = useMemo(
    () => bookBalances({ bets: view.bets, cash: view.cash }),
    [view.bets, view.cash],
  );
  const total = useMemo(() => totals(balances), [balances]);
  const kpi = useMemo(
    () => kpis(filtered, windowDays == null ? null : now - windowDays * DAY),
    // `now` moves once a minute, which is fine granularity for a day-sized window.
    [filtered, windowDays, now],
  );
  const bookCodes = useMemo(
    () => [...new Set(view.bets.map((b) => b.book))],
    [view.bets],
  );
  const bookItems = useMemo(
    () =>
      bookCodes
        .map((c): [string, string] => [c, bookLabel(c)])
        .sort((a, b) => a[1].localeCompare(b[1])),
    [bookCodes],
  );
  const leagueItems = useMemo(
    () =>
      [...new Set(view.bets.map((b) => b.sport_key))]
        .map((k): [string, string] => [k, leagueLabel(k)])
        .sort((a, b) => a[1].localeCompare(b[1])),
    [view.bets],
  );

  const open =
    panel?.kind === "bet"
      ? (view.bets.find((b) => b.id === panel.id) ?? null)
      : null;
  useEffect(() => {
    if (panel?.kind === "bet" && phase === "ready" && !open) setPanel(null);
  }, [panel, open, phase]);
  const siblings = useMemo(
    () =>
      open?.group_id
        ? view.bets.filter(
            (b) => b.group_id === open.group_id && b.id !== open.id,
          )
        : [],
    [open, view.bets],
  );

  const f = view.filters;
  return (
    <main className="personal-workspace trk-page">
      <header className="personal-header">
        <Link href="/games">
          <Image
            src="/assets/corner-logo.png"
            width={64}
            height={64}
            alt="Coop's Corner"
          />
        </Link>
        <div>
          <p className="eyebrow">YOUR CORNER</p>
          <h1>Tracker &amp; bankroll</h1>
        </div>
        <Link href="/positive_ev">← Back to tools</Link>
      </header>

      {notice && (
        <div role="alert" className="arb-alert trk-notice">
          <span>{notice}</span>
          <button
            type="button"
            className="link-button"
            onClick={() => setNotice("")}
          >
            dismiss
          </button>
        </div>
      )}

      {phase === "loading" ? (
        <p className="trk-empty" role="status">
          Loading your tracker…
        </p>
      ) : phase === "error" ? (
        <div role="alert" className="arb-alert">
          <strong>The tracker is not available.</strong>
          <span>{loadError}</span>
          <button
            className="button secondary"
            onClick={() => {
              setPhase("loading");
              load(false);
            }}
          >
            Try again
          </button>
        </div>
      ) : (
        <>
          <div className="trk-top">
            <div
              className="arb-modes trk-tabs"
              role="group"
              aria-label="Tracker sections"
            >
              <button
                type="button"
                className={tab === "bets" ? "active" : ""}
                aria-pressed={tab === "bets"}
                onClick={() => setTab("bets")}
              >
                Bets
              </button>
              <button
                type="button"
                className={tab === "bankroll" ? "active" : ""}
                aria-pressed={tab === "bankroll"}
                onClick={() => setTab("bankroll")}
              >
                Bankroll
              </button>
            </div>
            <label className="field trk-window">
              <span>PERFORMANCE WINDOW</span>
              <select
                value={windowDays ?? ""}
                onChange={(e) =>
                  setWindowDays(e.target.value ? Number(e.target.value) : null)
                }
              >
                <option value="7">Last 7 days</option>
                <option value="30">Last 30 days</option>
                <option value="">All time</option>
              </select>
            </label>
            <button
              className="button"
              onClick={() => setPanel({ kind: "log" })}
            >
              + Log a bet
            </button>
          </div>

          <KpiRibbon
            kpi={kpi}
            bankroll={total.bankroll}
            pendingTotal={total.pending}
          />

          {tab === "bankroll" ? (
            <BankrollTab
              bets={view.bets}
              cash={view.cash}
              onAddCash={addCashEntry}
              onDeleteCash={removeCash}
            />
          ) : (
            <>
              <div className="arb-bar trk-filters">
                <PickMenu
                  title="Sportsbooks"
                  items={bookItems}
                  picked={f.books}
                  onChange={(books) => setFilters({ books })}
                />
                <PickMenu
                  title="Leagues"
                  items={leagueItems}
                  picked={f.leagues}
                  onChange={(leagues) => setFilters({ leagues })}
                />
                <label className="field mid-small">
                  <span>STATUS</span>
                  <select
                    value={f.status}
                    onChange={(e) =>
                      setFilters({
                        status: e.target.value as Filters["status"],
                      })
                    }
                  >
                    <option value="all">All</option>
                    <option value="active">Active</option>
                    <option value="settled">Settled</option>
                    <option value="won">Won</option>
                    <option value="lost">Lost</option>
                    <option value="push">Push</option>
                    <option value="void">Void</option>
                    <option value="cashout">Cashed out</option>
                  </select>
                </label>
                <label className="field mid-small">
                  <span>STRATEGY</span>
                  <select
                    value={f.strategy}
                    onChange={(e) =>
                      setFilters({
                        strategy: e.target.value as Filters["strategy"],
                      })
                    }
                  >
                    <option value="all">All</option>
                    {Object.entries(STRATEGY_LABEL).map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field trk-search">
                  <span>SEARCH</span>
                  <input
                    type="search"
                    value={f.query}
                    placeholder="Player, team, market…"
                    onChange={(e) => setFilters({ query: e.target.value })}
                  />
                </label>
                {filtersActive(f) && (
                  <button
                    type="button"
                    className="button secondary"
                    onClick={() => setFilters(EMPTY_FILTERS)}
                  >
                    Clear filters
                  </button>
                )}
              </div>

              {view.bets.length === 0 ? (
                <div className="empty-state">
                  <h3>No bets yet</h3>
                  <p>
                    Use One-click bet in any tool to record a play with its
                    odds, edge and teams, or log one by hand. Deposits on the
                    Bankroll tab let Kelly size bets against your real balances.
                  </p>
                  <button
                    className="button"
                    onClick={() => setPanel({ kind: "log" })}
                  >
                    + Log a bet
                  </button>
                </div>
              ) : ordered.length === 0 ? (
                <div className="empty-state">
                  <h3>No bets match these filters</h3>
                  <button
                    className="button secondary"
                    onClick={() => setFilters(EMPTY_FILTERS)}
                  >
                    Clear filters
                  </button>
                </div>
              ) : (
                <>
                  <p className="trk-count" aria-live="polite">
                    <strong>{ordered.length}</strong> of {view.bets.length} bets
                    {watching && (
                      <span className="trk-livedot"> · live tracking on</span>
                    )}
                  </p>
                  <div className="trk-wrap">
                    <table className="trk-table" aria-label="Bet ledger">
                      <thead>
                        <tr>
                          <th>Date / event</th>
                          <th>Book</th>
                          <th>Strategy</th>
                          <th>Selection &amp; live progress</th>
                          <th className="trk-num">Odds</th>
                          <th className="trk-num">Stake</th>
                          <th className="trk-num">Result</th>
                          <th className="trk-num">CLV</th>
                        </tr>
                      </thead>
                      <tbody>
                        {ordered.slice(0, shown).map((bet) => (
                          <BetRow
                            key={bet.id}
                            bet={bet}
                            live={view.live[bet.id]}
                            selected={open?.id === bet.id}
                            onSelect={select}
                            onApply={apply}
                          />
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {ordered.length > shown && (
                    <button
                      type="button"
                      className="button secondary"
                      onClick={() => setShown((n) => n + PAGE)}
                    >
                      Show more ({ordered.length - shown} more)
                    </button>
                  )}
                </>
              )}
            </>
          )}
        </>
      )}

      <BookList codes={bookCodes} />
      <BetDrawer
        bet={open}
        live={open ? view.live[open.id] : undefined}
        siblings={siblings}
        onClose={closePanel}
        onSettle={settle}
        onReopen={reopen}
        onDelete={remove}
        onUpdate={update}
      />
      <LogDrawer
        open={panel?.kind === "log"}
        rows={balances}
        bankroll={total.bankroll}
        hasCash={view.cash.length > 0}
        onClose={closePanel}
        onSubmit={logManual}
      />
    </main>
  );
}

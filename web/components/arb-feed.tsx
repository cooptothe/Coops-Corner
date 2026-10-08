"use client";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ageLabel,
  american,
  compareDecimal,
  date,
  divDecimal,
  percent,
  selection,
  shiftDecimal,
  sport,
  usd,
} from "../../frontend/format.mjs";
import { allPages } from "../lib/api";
import {
  type ArbMode,
  type ArbSizing,
  biasedStakes,
  symmetricStakes,
} from "../lib/arb-math";
import type {
  Capabilities,
  Game,
  Meta,
  Quote,
  ToolRow,
} from "../lib/contracts";
import { ErrorCard, Loading } from "./workspace";

type ArbRow = Extract<ToolRow, { kind: "arbitrage" }>;
type Data = { caps: Capabilities; games: Game[]; quotes: Quote[]; meta: Meta };
interface LegVm {
  quoteId: string;
  bookId: string;
  bookLabel: string;
  label: string;
  decimalOdds: string;
  odds: string;
  lay: boolean;
}
interface BackLayVm {
  capital: number;
  backStake: number;
  layStake: number;
  liability: number;
  profit: number;
}
interface Vm {
  id: string;
  matchup: string;
  league: string;
  startsAt: string;
  sportKey: string;
  profit: string;
  legs: LegVm[];
  sig: string;
  observedAt: string;
  backLay: BackLayVm | null;
}

type SortKey = "profit" | "time" | "scanned";
const SORT_LABELS: [SortKey, string][] = [
  ["profit", "Profit % (highest)"],
  ["time", "Event time (soonest)"],
  ["scanned", "Newest scan"],
];
const startMs = (v: Vm) =>
  v.startsAt ? new Date(v.startsAt).getTime() : Infinity;
const SORTS: Record<SortKey, (a: Vm, b: Vm) => number> = {
  profit: (a, b) => compareDecimal(b.profit, a.profit),
  time: (a, b) => startMs(a) - startMs(b),
  scanned: (a, b) => b.observedAt.localeCompare(a.observedAt),
};
const ROW_HEIGHT = { wide: 88, compact: 190 };
const OVERSCAN = 6;
const SETTINGS_KEY = "corner.arb-settings";
const STAKE_PATTERN = /^\d{1,9}(\.\d{1,2})?$/;
const PROFIT_PATTERN = /^\d{1,2}(\.\d{1,2})?$/;
export const shortBook = (name: string) =>
  name.replace("Demo ", "").replace("Reference ", "Ref ");

function toVm(
  row: ArbRow,
  quotes: Map<string, Quote>,
  games: Map<string, Game>,
  books: Map<string, string>,
): Vm | null {
  if (row.minimum_profit == null) return null;
  const calc = row.calculation;
  const ids =
    "back_quote_id" in calc
      ? [calc.back_quote_id, calc.lay_quote_id]
      : calc.legs.map((l) => l.quote_id);
  const legs: LegVm[] = [];
  for (const id of ids) {
    const q = quotes.get(id);
    if (!q) return null;
    legs.push({
      quoteId: id,
      bookId: q.sportsbook_id,
      bookLabel: shortBook(books.get(q.sportsbook_id) ?? q.sportsbook_id),
      label: selection(q),
      decimalOdds: q.decimal_odds,
      odds: american(q.decimal_odds),
      lay: q.market_key.endsWith("_lay"),
    });
  }
  if (legs.length !== 2) return null;
  let profit: string;
  try {
    profit = divDecimal(row.minimum_profit, row.capital_required);
  } catch {
    return null;
  }
  const g = games.get(row.game_id);
  return {
    id: row.id,
    matchup: g?.name ?? "Event",
    league: g?.competition ?? sport(g?.sport_key ?? ""),
    startsAt: g?.starts_at ?? "",
    sportKey: g?.sport_key ?? "",
    profit,
    legs,
    sig: legs.map((l) => `${l.quoteId}@${l.decimalOdds}`).join("|"),
    observedAt: row.oldest_observed_at,
    backLay:
      "back_quote_id" in calc
        ? {
            capital: Number(row.capital_required),
            backStake: Number(calc.back_stake),
            layStake: Number(calc.lay_stake),
            liability: Number(calc.lay_liability),
            profit: Number(row.minimum_profit),
          }
        : null,
  };
}

export function Age({ value }: { value: string }) {
  const [, tick] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(timer);
  }, []);
  return <span className="ev-age">{ageLabel(value)}</span>;
}

const Row = memo(
  function Row({
    vm,
    top,
    selected,
    onSelect,
  }: {
    vm: Vm;
    top: number;
    selected: boolean;
    onSelect: (vm: Vm) => void;
  }) {
    return (
      <div
        role="row"
        tabIndex={0}
        aria-selected={selected}
        className={`ev-row ${selected ? "selected" : ""}`}
        style={{ transform: `translateY(${top}px)` }}
        onClick={() => onSelect(vm)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onSelect(vm);
          }
        }}
      >
        <div role="cell" className="ev-cell ev-edge">
          <span className="ev-badge arb-badge">{percent(vm.profit, true)}</span>
        </div>
        <div role="cell" className="ev-cell ev-event">
          <span className="ev-league">{vm.league}</span>
          <strong>{vm.matchup}</strong>
          <small>{vm.startsAt ? date(vm.startsAt) : ""}</small>
        </div>
        <div role="cell" className="ev-cell arb-legs">
          {vm.legs.map((l) => (
            <div className="arb-leg" key={l.quoteId}>
              <span className="arb-book">{l.bookLabel}</span>
              <span className="arb-side">{l.label}</span>
              <b>{l.odds}</b>
            </div>
          ))}
        </div>
        <div role="cell" className="ev-cell ev-time">
          <Age value={vm.observedAt} />
        </div>
      </div>
    );
  },
  (a, b) =>
    a.vm.id === b.vm.id &&
    a.vm.sig === b.vm.sig &&
    a.vm.profit === b.vm.profit &&
    a.vm.observedAt === b.vm.observedAt &&
    a.top === b.top &&
    a.selected === b.selected,
);

export function CopyButton({ value, label }: { value: string; label: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      className="button secondary arb-copy"
      aria-label={`Copy ${label} stake`}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setDone(true);
          setTimeout(() => setDone(false), 1200);
        } catch {}
      }}
    >
      {done ? "Copied" : "Copy"}
    </button>
  );
}

function Calculator({
  vm,
  shift,
  onAccept,
  stake,
  setStake,
  onClose,
}: {
  vm: Vm | null;
  shift: "ok" | "moved" | "dropped";
  onAccept: () => void;
  stake: string;
  setStake: (v: string) => void;
  onClose: () => void;
}) {
  const [mode, setMode] = useState<ArbMode>("symmetric");
  // The calculator is a drawer, so Escape closes it.
  useEffect(() => {
    if (!vm) return;
    const close = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [vm, onClose]);
  const [favored, setFavored] = useState(0);
  const sig = vm?.sig ?? "";
  const validStake = STAKE_PATTERN.test(stake) && Number(stake) > 0;
  const total = validStake ? Number(stake) : 0;
  // Recalculate only when the stake, mode, favored leg or this row's own prices change.
  const sizing: ArbSizing | null = useMemo(() => {
    if (!vm || vm.backLay || !total) return null;
    const odds = vm.legs.map((l) => Number(l.decimalOdds));
    return mode === "symmetric"
      ? symmetricStakes(total, odds)
      : biasedStakes(total, odds, favored);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig, total, mode, favored]);
  const lay = useMemo(() => {
    if (!vm?.backLay || !total) return null;
    const k = total / vm.backLay.capital;
    return {
      back: vm.backLay.backStake * k,
      layStake: vm.backLay.layStake * k,
      liability: vm.backLay.liability * k,
      profit: vm.backLay.profit * k,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig, total]);

  return (
    <aside
      className={`kelly-panel arb-calc ${vm ? "open" : ""}`}
      aria-label="Arbitrage calculator"
      style={{ background: "#2e2a2a" }}
    >
      <button className="kelly-close" onClick={onClose} aria-label="Close">
        ✕
      </button>
      <h3>Arbitrage calculator</h3>
      {!vm ? (
        <p className="kelly-empty">Select an opportunity to size the stakes.</p>
      ) : (
        <>
          {shift !== "ok" && (
            <div role="alert" className="arb-alert">
              <strong>
                {shift === "dropped"
                  ? "This line is no longer available."
                  : "The line has shifted."}
              </strong>
              <span>
                {shift === "dropped"
                  ? "A sportsbook changed or dropped a price after the latest refresh. The numbers below are the old prices."
                  : "A sportsbook changed its odds after the latest refresh."}
              </span>
              {shift === "moved" && (
                <button className="button secondary" onClick={onAccept}>
                  Use the updated prices
                </button>
              )}
            </div>
          )}
          <div className="kelly-head">
            <strong>{vm.matchup}</strong>
            <span>{vm.league}</span>
            <span className="ev-badge arb-badge">
              {percent(vm.profit, true)}
            </span>
          </div>
          <label className="field">
            <span>TOTAL STAKE ($)</span>
            <input
              inputMode="decimal"
              value={stake}
              maxLength={12}
              aria-invalid={!validStake}
              onChange={(e) => setStake(e.target.value.trim())}
            />
          </label>
          {!vm.backLay && (
            <div className="arb-modes" role="group" aria-label="Mode">
              <button
                type="button"
                className={mode === "symmetric" ? "active" : ""}
                aria-pressed={mode === "symmetric"}
                onClick={() => setMode("symmetric")}
              >
                Symmetric
              </button>
              <button
                type="button"
                className={mode === "biased" ? "active" : ""}
                aria-pressed={mode === "biased"}
                onClick={() => setMode("biased")}
              >
                Biased
              </button>
            </div>
          )}
          {mode === "biased" && !vm.backLay && (
            <label className="field">
              <span>MAXIMIZE PROFIT IF THIS WINS</span>
              <select
                value={favored}
                onChange={(e) => setFavored(Number(e.target.value))}
              >
                {vm.legs.map((l, i) => (
                  <option key={l.quoteId} value={i}>
                    {l.label} · {l.bookLabel}
                  </option>
                ))}
              </select>
            </label>
          )}
          {!validStake ? (
            <p className="kelly-empty">Enter a stake greater than zero.</p>
          ) : vm.backLay && lay ? (
            <>
              <div className="arb-stake">
                <span>
                  Back · {vm.legs[0].bookLabel} {vm.legs[0].label}
                </span>
                <output>{usd(lay.back.toFixed(2))}</output>
                <CopyButton value={lay.back.toFixed(2)} label="back" />
              </div>
              <div className="arb-stake">
                <span>
                  Lay · {vm.legs[1].bookLabel} {vm.legs[1].label}
                </span>
                <output>{usd(lay.layStake.toFixed(2))}</output>
                <CopyButton value={lay.layStake.toFixed(2)} label="lay" />
              </div>
              <small className="kelly-note">
                Lay liability {usd(lay.liability.toFixed(2))}. Scaled from the
                tool's stakes; the stake box is the capital at risk.
              </small>
              <div className="arb-summary">
                <span>Total risked</span>
                <b>{usd(total.toFixed(2))}</b>
                <span>Gross guaranteed return</span>
                <b>{usd((total + lay.profit).toFixed(2))}</b>
                <span>Net profit</span>
                <b className="arb-net">{usd(lay.profit.toFixed(2))}</b>
              </div>
            </>
          ) : sizing ? (
            <>
              {sizing.stakes.map((s, i) => (
                <div className="arb-stake" key={vm.legs[i].quoteId}>
                  <span>
                    Leg {String.fromCharCode(65 + i)} · {vm.legs[i].bookLabel}{" "}
                    {vm.legs[i].label} @ {vm.legs[i].odds}
                  </span>
                  <output>{usd(s.toFixed(2))}</output>
                  <CopyButton
                    value={s.toFixed(2)}
                    label={`leg ${String.fromCharCode(65 + i)}`}
                  />
                </div>
              ))}
              <div className="arb-summary">
                <span>Total risked</span>
                <b>{usd(sizing.totalStake.toFixed(2))}</b>
                <span>Gross guaranteed return</span>
                <b>{usd(sizing.guaranteedReturn.toFixed(2))}</b>
                <span>Net profit</span>
                <b className="arb-net">{usd(sizing.netProfit.toFixed(2))}</b>
                {mode === "biased" && (
                  <>
                    <span>If {vm.legs[favored].label} wins</span>
                    <b>{usd(sizing.bestProfit.toFixed(2))}</b>
                  </>
                )}
              </div>
              {mode === "biased" && (
                <small className="kelly-note">
                  Biased: the other legs only return your total stake.
                </small>
              )}
            </>
          ) : (
            <p className="kelly-empty">
              These prices no longer form a profitable arbitrage.
            </p>
          )}
          <small className="kelly-note">
            Calculation only. Nothing is placed at a sportsbook; confirm each
            price there first.
          </small>
        </>
      )}
    </aside>
  );
}

export function Menu({
  title,
  items,
  off,
  setOff,
}: {
  title: string;
  items: [string, string][];
  off: Set<string>;
  setOff: (next: Set<string>) => void;
}) {
  return (
    <details className="arb-menu">
      <summary>
        {title} ({items.filter(([id]) => !off.has(id)).length}/{items.length})
      </summary>
      <div className="arb-menu-pop">
        <div>
          <button
            type="button"
            className="link-button"
            onClick={() => setOff(new Set())}
          >
            all
          </button>{" "}
          <button
            type="button"
            className="link-button"
            onClick={() => setOff(new Set(items.map(([id]) => id)))}
          >
            none
          </button>
        </div>
        {items.map(([id, label]) => (
          <label key={id}>
            <input
              type="checkbox"
              checked={!off.has(id)}
              onChange={() => {
                const next = new Set(off);
                if (!next.delete(id)) next.add(id);
                setOff(next);
              }}
            />
            {label}
          </label>
        ))}
        {items.length === 0 && <small>None yet.</small>}
      </div>
    </details>
  );
}

export default function ArbFeed({ data }: { data: Data }) {
  const [rows, setRows] = useState<ArbRow[] | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [offBooks, setOffBooks] = useState<Set<string>>(new Set());
  const [offSports, setOffSports] = useState<Set<string>>(new Set());
  const [minProfit, setMinProfit] = useState("0");
  const [sortKey, setSortKey] = useState<SortKey>("profit");
  const [stake, setStake] = useState("100");
  const [selected, setSelected] = useState<Vm | null>(null);

  useEffect(() => {
    try {
      const s = JSON.parse(localStorage.getItem(SETTINGS_KEY) ?? "{}");
      if (Array.isArray(s.offBooks))
        setOffBooks(new Set(s.offBooks.map(String)));
      if (Array.isArray(s.offSports))
        setOffSports(new Set(s.offSports.map(String)));
      if (typeof s.sortKey === "string" && s.sortKey in SORTS)
        setSortKey(s.sortKey as SortKey);
      if (typeof s.minProfit === "string" && PROFIT_PATTERN.test(s.minProfit))
        setMinProfit(s.minProfit);
      if (typeof s.stake === "string" && STAKE_PATTERN.test(s.stake))
        setStake(s.stake);
    } catch {}
  }, []);
  useEffect(() => {
    localStorage.setItem(
      SETTINGS_KEY,
      JSON.stringify({
        offBooks: [...offBooks],
        offSports: [...offSports],
        minProfit,
        stake,
        sortKey,
      }),
    );
  }, [offBooks, offSports, minProfit, stake, sortKey]);

  useEffect(() => {
    const controller = new AbortController();
    setError("");
    allPages<ToolRow>(
      "tools/arbitrage",
      data.meta.snapshot_id,
      controller.signal,
    )
      .then((items) => {
        if (!controller.signal.aborted)
          setRows(items.filter((r): r is ArbRow => r.kind === "arbitrage"));
      })
      .catch((e) => {
        if (!controller.signal.aborted)
          setError(e instanceof Error ? e.message : "Request failed.");
      });
    return () => controller.abort();
  }, [data, retry]);

  const maps = useMemo(
    () => ({
      quotes: new Map(data.quotes.map((q) => [q.id, q])),
      games: new Map(data.games.map((g) => [g.id, g])),
      books: new Map(data.caps.books.map((b) => [b.id, b.name])),
    }),
    [data],
  );
  const all = useMemo(
    () =>
      (rows ?? [])
        .map((r) => toVm(r, maps.quotes, maps.games, maps.books))
        .filter((v): v is Vm => v !== null)
        .sort(SORTS.profit),
    [rows, maps],
  );
  const byId = useMemo(() => new Map(all.map((v) => [v.id, v])), [all]);
  const bookItems = useMemo(
    () =>
      data.caps.books
        .map((b): [string, string] => [b.id, shortBook(b.name)])
        .sort((a, b) => a[1].localeCompare(b[1])),
    [data],
  );
  const sportItems = useMemo(() => {
    const m = new Map<string, string>();
    for (const g of data.games)
      m.set(g.sport_key, g.competition ?? sport(g.sport_key));
    for (const v of all) m.set(v.sportKey, m.get(v.sportKey) ?? v.league);
    return [...m].sort((a, b) => a[1].localeCompare(b[1]));
  }, [data, all]);

  const minRatio = shiftDecimal(
    PROFIT_PATTERN.test(minProfit) ? minProfit : "0",
    -2,
  );
  const visible = useMemo(
    () =>
      all
        .filter(
          (v) =>
            !offSports.has(v.sportKey) &&
            v.legs.every((l) => !offBooks.has(l.bookId)) &&
            compareDecimal(v.profit, minRatio) >= 0,
        )
        .sort(SORTS[sortKey]),
    [all, offBooks, offSports, minRatio, sortKey],
  );

  const [compact, setCompact] = useState(false);
  useEffect(() => {
    const media = matchMedia("(max-width:900px)");
    const change = () => setCompact(media.matches);
    change();
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, []);
  const height = compact ? ROW_HEIGHT.compact : ROW_HEIGHT.wide;
  const viewport = useRef<HTMLDivElement>(null);
  const [scroll, setScroll] = useState(0);
  const frame = useRef(0);
  const onScroll = useCallback(() => {
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() =>
      setScroll(viewport.current?.scrollTop ?? 0),
    );
  }, []);
  useEffect(() => () => cancelAnimationFrame(frame.current), []);
  const viewHeight = 680;
  const first = Math.max(0, Math.floor(scroll / height) - OVERSCAN);
  const last = Math.min(
    visible.length,
    Math.ceil((scroll + viewHeight) / height) + OVERSCAN,
  );
  const select = useCallback((vm: Vm) => setSelected(vm), []);

  const current = selected ? (byId.get(selected.id) ?? null) : null;
  const shift: "ok" | "moved" | "dropped" = !selected
    ? "ok"
    : !current
      ? "dropped"
      : current.sig !== selected.sig
        ? "moved"
        : "ok";
  const shown = shift === "moved" ? selected : (current ?? selected);

  if (error)
    return <ErrorCard message={error} retry={() => setRetry((n) => n + 1)} />;
  if (!rows) return <Loading text="Scanning for arbitrage…" />;

  return (
    <section className="arb-layout" aria-label="Arbitrage feed">
      <div className="arb-bar">
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
        <label className="field arb-min">
          <span>MIN. PROFIT · {minProfit || "0"}%</span>
          <span className="arb-min-inputs">
            <input
              type="range"
              min="0"
              max="10"
              step="0.25"
              value={PROFIT_PATTERN.test(minProfit) ? minProfit : "0"}
              onChange={(e) => setMinProfit(e.target.value)}
            />
            <input
              inputMode="decimal"
              value={minProfit}
              maxLength={5}
              aria-invalid={!PROFIT_PATTERN.test(minProfit)}
              onChange={(e) => setMinProfit(e.target.value.trim())}
            />
          </span>
        </label>
        <label className="field mid-small">
          <span>SORT BY</span>
          <select
            value={sortKey}
            onChange={(e) => setSortKey(e.target.value as SortKey)}
          >
            {SORT_LABELS.map(([k, l]) => (
              <option key={k} value={k}>
                {l}
              </option>
            ))}
          </select>
        </label>
        <span className="arb-status" role="status">
          <i className="arb-pulse" aria-hidden="true" />
          Connected · prices as of {date(data.meta.captured_at)}
        </span>
      </div>
      <div className="arb-body">
        <div className="ev-main">
          <div className="ev-count">
            <strong>{visible.length}</strong> of {all.length} opportunities ·
            best first
          </div>
          <div
            role="table"
            aria-label="Arbitrage opportunities"
            className="ev-grid arb-grid"
          >
            <div role="row" className="ev-head">
              <span role="columnheader">Profit</span>
              <span role="columnheader">Event</span>
              <span role="columnheader">Legs</span>
              <span role="columnheader">Scanned</span>
            </div>
            {visible.length === 0 ? (
              <div className="empty-state">
                <h3>No arbitrage right now</h3>
                <p>
                  Lower the minimum profit, re-enable books or leagues, or press
                  Refresh odds. Real arbitrage is rare and short-lived.
                </p>
              </div>
            ) : (
              <div
                ref={viewport}
                className="ev-viewport"
                style={{
                  height: Math.min(viewHeight, visible.length * height),
                }}
                onScroll={onScroll}
              >
                <div
                  className="ev-spacer"
                  role="rowgroup"
                  style={{ height: visible.length * height }}
                >
                  {visible.slice(first, last).map((vm, i) => (
                    <Row
                      key={vm.id}
                      vm={vm}
                      top={(first + i) * height}
                      selected={vm.id === selected?.id}
                      onSelect={select}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
        {selected && (
          <div className="kelly-backdrop" onClick={() => setSelected(null)} />
        )}
        <Calculator
          vm={shown}
          shift={shift}
          onAccept={() => current && setSelected(current)}
          stake={stake}
          setStake={setStake}
          onClose={() => setSelected(null)}
        />
      </div>
    </section>
  );
}

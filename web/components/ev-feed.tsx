"use client";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  MARKETS,
  american,
  compareDecimal,
  date,
  divDecimal,
  mulDecimal,
  percent,
  selection,
  shiftDecimal,
  sport,
  subDecimal,
  usd,
  ageLabel,
} from "../../frontend/format.mjs";
import { allPages } from "../lib/api";
import type {
  Capabilities,
  Game,
  Meta,
  Quote,
  ToolRow,
} from "../lib/contracts";
import { logBets } from "../lib/slip";
import { SlipLog, SlipToggle, useSlip } from "./bet-slip";
import { Avatar, Matchup } from "./media";
import { ErrorCard, Loading } from "./workspace";

type EvRow = Extract<ToolRow, { kind: "positive_ev" }>;
type Flash = "up" | "down";
interface Vm {
  id: string;
  gameId: string;
  matchup: string;
  league: string;
  startsAt: string;
  sportKey: string;
  market: string;
  line: string;
  bookId: string;
  bookLabel: string;
  lay: boolean;
  ev: string;
  decimalOdds: string;
  odds: string;
  fairOdds: string | null;
  prob: number;
  startMs: number;
  sharps: string;
  observedAt: string;
}
export interface KellyVm {
  id: string;
  sportKey: string;
  // Set for player props, so the calculator can show the headshot.
  player?: string;
  matchup: string;
  market: string;
  line: string;
  ev: string;
  bookLabel: string;
  odds: string;
  decimalOdds: string;
  lay: boolean;
}
type Data = { caps: Capabilities; games: Game[]; quotes: Quote[]; meta: Meta };

const ROW_HEIGHT = { wide: 88, compact: 244 };
const OVERSCAN = 6;
const SHARP_BOOKS = new Set([
  "pinnacle",
  "betfair_ex_uk",
  "prophetx",
  "kalshi",
]);
export const BANKROLL_KEY = "corner.bankroll";
export const MULTIPLIER_KEY = "corner.kelly";
const SETTINGS_KEY = "corner.ev-settings";
const oddsToDecimal = (v: string) => {
  if (!/^-?\d{2,5}$/.test(v)) return null;
  const n = Number(v);
  if (Math.abs(n) < 100) return null;
  return n > 0 ? 1 + n / 100 : 1 + 100 / -n;
};

const shortBook = (name: string) =>
  name.replace("Demo ", "").replace("Reference ", "Ref ");

function fairAmerican(probability: string) {
  try {
    return american(divDecimal("1", probability));
  } catch {
    return null;
  }
}

function toVm(
  row: EvRow,
  quotes: Map<string, Quote>,
  games: Map<string, Game>,
  books: Map<string, string>,
): Vm | null {
  const q = quotes.get(row.calculation.target_quote_id);
  if (!q || row.conditional_ev_ratio == null) return null;
  const g = games.get(row.game_id);
  const sharps = row.calculation.reference_books
    .map((b) => shortBook(books.get(b.sportsbook_id) ?? b.sportsbook_id))
    .join(" + ");
  return {
    id: row.id,
    gameId: row.game_id,
    matchup: g?.name ?? "Event",
    league: g?.competition ?? sport(g?.sport_key ?? ""),
    startsAt: g?.starts_at ?? "",
    sportKey: g?.sport_key ?? "",
    market: MARKETS[row.market_key as keyof typeof MARKETS] ?? row.market_key,
    line: selection(q),
    bookId: q.sportsbook_id,
    bookLabel: shortBook(books.get(q.sportsbook_id) ?? q.sportsbook_id),
    lay: q.market_key.endsWith("_lay"),
    ev: row.conditional_ev_ratio,
    decimalOdds: q.decimal_odds,
    odds: american(q.decimal_odds),
    fairOdds: fairAmerican(row.calculation.conditional_fair_probability),
    prob: Number(row.calculation.conditional_fair_probability),
    startMs: g?.starts_at ? new Date(g.starts_at).getTime() : Infinity,
    sharps,
    observedAt: row.oldest_observed_at,
  };
}

// Fractional Kelly on a back bet, uncapped. Lay bets get no suggestion.
export function kelly(
  edge: string,
  decimalOdds: string,
  bankroll: string,
  multiplier: string,
  lay: boolean,
) {
  if (lay) return null;
  const net = subDecimal(decimalOdds, "1");
  if (compareDecimal(edge, "0") <= 0 || compareDecimal(net, "0") <= 0)
    return null;
  const fraction = mulDecimal(divDecimal(edge, net), multiplier);
  return { fraction, stake: mulDecimal(bankroll, fraction) };
}

function Age({ value }: { value: string }) {
  const [, tick] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(timer);
  }, []);
  return <span className="ev-age">{ageLabel(value)}</span>;
}

type SortKey =
  | "ev"
  | "chance_high"
  | "chance_low"
  | "time"
  | "odds_high"
  | "odds_low"
  | "scanned";
const SORT_LABELS: [SortKey, string][] = [
  ["ev", "EV % (highest)"],
  ["chance_high", "Win chance (most likely)"],
  ["chance_low", "Win chance (longshots)"],
  ["time", "Event time (soonest)"],
  ["odds_high", "Odds (highest payout)"],
  ["odds_low", "Odds (shortest price)"],
  ["scanned", "Newest scan"],
];
const SORTS: Record<SortKey, (a: Vm, b: Vm) => number> = {
  ev: (a, b) => compareDecimal(b.ev, a.ev),
  chance_high: (a, b) => b.prob - a.prob,
  chance_low: (a, b) => a.prob - b.prob,
  time: (a, b) => a.startMs - b.startMs,
  odds_high: (a, b) => Number(b.decimalOdds) - Number(a.decimalOdds),
  odds_low: (a, b) => Number(a.decimalOdds) - Number(b.decimalOdds),
  scanned: (a, b) => b.observedAt.localeCompare(a.observedAt),
};
const chance = (p: number) => `${(p * 100).toFixed(2)}%`;

const Row = memo(
  function Row({
    vm,
    top,
    selected,
    flash,
    onSelect,
  }: {
    vm: Vm;
    top: number;
    selected: boolean;
    flash?: { odds?: Flash; ev?: Flash; tick: number };
    onSelect: (id: string) => void;
  }) {
    return (
      <div
        role="row"
        tabIndex={0}
        aria-selected={selected}
        className={`ev-row ev-tall ${selected ? "selected" : ""}`}
        style={{ transform: `translateY(${top}px)` }}
        onClick={() => onSelect(vm.id)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onSelect(vm.id);
          }
        }}
      >
        <div role="cell" className="ev-cell ev-edge">
          <span
            key={`ev-${flash?.tick ?? 0}`}
            className={`ev-badge ${flash?.ev ? `flash-${flash.ev}` : ""}`}
          >
            {percent(vm.ev, true)}
          </span>
        </div>
        <div role="cell" className="ev-cell ev-event">
          <span className="ev-league">{vm.league}</span>
          <Matchup text={vm.matchup} sportKey={vm.sportKey} />
          <small>{vm.startsAt ? date(vm.startsAt) : ""}</small>
        </div>
        <div role="cell" className="ev-cell ev-market">
          <small>{vm.market}</small>
          <strong>{vm.line}</strong>
        </div>
        <div role="cell" className="ev-cell ev-soft">
          <span
            key={`odds-${flash?.tick ?? 0}`}
            className={`ev-action ${flash?.odds ? `flash-${flash.odds}` : ""}`}
          >
            <span>{vm.bookLabel}</span>
            <b>@ {vm.odds}</b>
          </span>
        </div>
        <div role="cell" className="ev-cell ev-sharp">
          <strong>{chance(vm.prob)} chance</strong>
          <small>
            Fair {vm.fairOdds ?? "—"} · {vm.sharps}
          </small>
        </div>
        <div role="cell" className="ev-cell ev-time">
          <Age value={vm.observedAt} />
        </div>
      </div>
    );
  },
  (a, b) =>
    a.vm.id === b.vm.id &&
    a.vm.ev === b.vm.ev &&
    a.vm.decimalOdds === b.vm.decimalOdds &&
    a.vm.observedAt === b.vm.observedAt &&
    a.top === b.top &&
    a.selected === b.selected &&
    a.flash?.tick === b.flash?.tick,
);

export function KellyWidget({
  vm,
  bankroll,
  setBankroll,
  multiplier,
  setMultiplier,
  onClose,
  onLogged,
}: {
  onLogged: () => void;
  vm: KellyVm | null;
  bankroll: string;
  setBankroll: (v: string) => void;
  multiplier: string;
  setMultiplier: (v: string) => void;
  onClose: () => void;
}) {
  const [bet, setBet] = useState<"idle" | "pending" | "done">("idle");
  useEffect(() => setBet("idle"), [vm?.id]);
  // The calculator is a drawer, so Escape closes it.
  useEffect(() => {
    if (!vm) return;
    const close = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [vm, onClose]);
  const validBankroll = /^(0|[1-9]\d{0,9})(\.\d{1,2})?$/.test(bankroll);
  const result =
    vm && validBankroll && compareDecimal(bankroll, "0") > 0
      ? kelly(vm.ev, vm.decimalOdds, bankroll, multiplier, vm.lay)
      : null;
  const place = () => {
    if (!vm || !result) return;
    setBet("pending");
    setTimeout(() => {
      try {
        logBets([
          {
            matchup: vm.matchup,
            line: vm.line,
            book: vm.bookLabel,
            odds: vm.odds,
            stake: result.stake,
          },
        ]);
      } catch {}
      setBet("done");
      onLogged();
    }, 700);
  };
  return (
    <aside
      className={`kelly-panel ${vm ? "open" : ""}`}
      aria-label="Kelly calculator"
      style={{ background: "#2e2a2a" }}
    >
      <button className="kelly-close" onClick={onClose} aria-label="Close">
        ✕
      </button>
      <h3>Kelly calculator</h3>
      {!vm ? (
        <p className="kelly-empty">Select a row to size the bet.</p>
      ) : (
        <>
          <div className="kelly-head">
            <Matchup text={vm.matchup} sportKey={vm.sportKey} size={22} />
            {vm.player && (
              <span className="player-chip">
                <Avatar
                  kind="player"
                  name={vm.player}
                  sportKey={vm.sportKey}
                  size={36}
                />
                <span>{vm.line}</span>
              </span>
            )}
            <span>
              {vm.market}
              {vm.player ? "" : ` · ${vm.line}`}
            </span>
            <span className="ev-badge">{percent(vm.ev, true)}</span>
            <small>
              {vm.bookLabel} @ {vm.odds}
            </small>
          </div>
          <label className="field">
            <span>TOTAL BANKROLL ($)</span>
            <input
              inputMode="decimal"
              value={bankroll}
              maxLength={13}
              onChange={(e) => setBankroll(e.target.value)}
              aria-invalid={!validBankroll}
            />
          </label>
          <label className="field">
            <span>
              KELLY MULTIPLIER · {multiplier}
              {multiplier === "0.25" ? " (quarter-Kelly)" : ""}
            </span>
            <input
              type="range"
              min="0.1"
              max="1"
              step="0.05"
              value={multiplier}
              onChange={(e) => setMultiplier(e.target.value)}
            />
          </label>
          <div className="kelly-result">
            <span>SUGGESTED STAKE</span>
            <strong className="kelly-stake">
              {result ? usd(result.stake) : "—"}
            </strong>
            <small>
              {result
                ? `${percent(result.fraction)} of bankroll`
                : vm.lay
                  ? "No suggestion for lay bets"
                  : "Enter a valid bankroll"}
            </small>
          </div>
          <button
            className="button kelly-bet"
            disabled={!result || bet === "pending"}
            onClick={place}
          >
            {bet === "pending"
              ? "Recording…"
              : bet === "done"
                ? "Logged ✓"
                : "One-click bet"}
          </button>
          <small className="kelly-note">
            {bet === "done"
              ? "Saved to the local slip only. Nothing was placed at the sportsbook — place it there and re-check the price."
              : "Simulated: records the bet locally. It does not place a wager."}
          </small>
        </>
      )}
    </aside>
  );
}

export default function EvFeed({ data }: { data: Data }) {
  const [rows, setRows] = useState<EvRow[] | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [offBooks, setOffBooks] = useState<Set<string>>(new Set());
  const [minEv, setMinEv] = useState("0");
  const [sortKey, setSortKey] = useState<SortKey>("ev");
  const [minOdds, setMinOdds] = useState("");
  const [maxOdds, setMaxOdds] = useState("");
  const {
    slip,
    open: slipOpen,
    setOpen: setSlipOpen,
    refresh: refreshSlip,
  } = useSlip();
  const [sportKey, setSportKey] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [bankroll, setBankroll] = useState("1000");
  const [multiplier, setMultiplier] = useState("0.25");
  const [flashes, setFlashes] = useState<
    Map<string, { odds?: Flash; ev?: Flash; tick: number }>
  >(new Map());
  const previous = useRef<Map<string, { odds: string; ev: string }>>(new Map());
  const tickRef = useRef(0);

  useEffect(() => {
    const b = localStorage.getItem(BANKROLL_KEY),
      m = localStorage.getItem(MULTIPLIER_KEY);
    if (b && /^[0-9.]{1,13}$/.test(b)) setBankroll(b);
    if (m && /^(0\.[1-9]\d?|1)$/.test(m)) setMultiplier(m);
    try {
      const s = JSON.parse(localStorage.getItem(SETTINGS_KEY) ?? "{}");
      if (Array.isArray(s.off)) setOffBooks(new Set(s.off.map(String)));
      if (typeof s.sortKey === "string" && s.sortKey in SORTS)
        setSortKey(s.sortKey as SortKey);
      if (typeof s.minEv === "string" && /^\d{1,2}(\.\d{1,2})?$/.test(s.minEv))
        setMinEv(s.minEv);
      if (typeof s.minOdds === "string" && /^-?\d{0,5}$/.test(s.minOdds))
        setMinOdds(s.minOdds);
      if (typeof s.maxOdds === "string" && /^-?\d{0,5}$/.test(s.maxOdds))
        setMaxOdds(s.maxOdds);
    } catch {}
  }, []);
  useEffect(() => {
    localStorage.setItem(
      SETTINGS_KEY,
      JSON.stringify({ off: [...offBooks], minEv, minOdds, maxOdds, sortKey }),
    );
  }, [offBooks, minEv, minOdds, maxOdds, sortKey]);
  useEffect(() => {
    localStorage.setItem(BANKROLL_KEY, bankroll);
  }, [bankroll]);
  useEffect(() => {
    localStorage.setItem(MULTIPLIER_KEY, multiplier);
  }, [multiplier]);

  useEffect(() => {
    const controller = new AbortController();
    setError("");
    allPages<ToolRow>(
      "tools/positive_ev",
      data.meta.snapshot_id,
      controller.signal,
    )
      .then((items) => {
        if (!controller.signal.aborted)
          setRows(items.filter((r): r is EvRow => r.kind === "positive_ev"));
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
        .sort(SORTS.ev),
    [rows, maps],
  );

  // Flash only the cells whose price or edge moved since the last snapshot.
  useEffect(() => {
    const next = new Map<string, { odds?: Flash; ev?: Flash; tick: number }>();
    for (const v of all) {
      const old = previous.current.get(v.id);
      if (!old) continue;
      const odds = compareDecimal(v.decimalOdds, old.odds);
      const ev = compareDecimal(v.ev, old.ev);
      if (odds || ev)
        next.set(v.id, {
          odds: odds ? (odds > 0 !== v.lay ? "up" : "down") : undefined,
          ev: ev ? (ev > 0 ? "up" : "down") : undefined,
          tick: ++tickRef.current,
        });
    }
    previous.current = new Map(
      all.map((v) => [v.id, { odds: v.decimalOdds, ev: v.ev }]),
    );
    if (next.size) {
      setFlashes(next);
      const timer = setTimeout(() => setFlashes(new Map()), 1500);
      return () => clearTimeout(timer);
    }
  }, [all]);

  const books = useMemo(() => {
    const list = new Map(all.map((v) => [v.bookId, v.bookLabel]));
    for (const b of data.caps.books)
      if (!SHARP_BOOKS.has(b.id)) list.set(b.id, shortBook(b.name));
    return [...list].sort((a, b) => a[1].localeCompare(b[1]));
  }, [all, data]);
  const sports = useMemo(() => {
    const m = new Map<string, string>();
    for (const v of all) if (v.sportKey) m.set(v.sportKey, v.league);
    return [...m].sort((a, b) => a[1].localeCompare(b[1]));
  }, [all]);
  const minRatio = shiftDecimal(minEv, -2);
  const lo = oddsToDecimal(minOdds);
  const hi = oddsToDecimal(maxOdds);
  const visible = useMemo(
    () =>
      all
        .filter(
          (v) =>
            !offBooks.has(v.bookId) &&
            (!sportKey || v.sportKey === sportKey) &&
            compareDecimal(v.ev, minRatio) >= 0 &&
            (lo === null || Number(v.decimalOdds) >= lo) &&
            (hi === null || Number(v.decimalOdds) <= hi),
        )
        .sort(SORTS[sortKey]),
    [all, offBooks, sportKey, minRatio, lo, hi, sortKey],
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
  const select = useCallback((id: string) => setSelected(id), []);
  const active = visible.find((v) => v.id === selected) ?? null;

  if (error)
    return <ErrorCard message={error} retry={() => setRetry((n) => n + 1)} />;
  if (!rows) return <Loading text="Scanning for +EV bets…" />;

  return (
    <section className="ev-layout" aria-label="Positive EV feed">
      <aside className="ev-filters" style={{ background: "#2e2a2a" }}>
        <h3>Filters</h3>
        <label className="field">
          <span>MIN. EV · {minEv}%</span>
          <input
            type="range"
            min="0"
            max="10"
            step="0.25"
            value={minEv}
            onChange={(e) => setMinEv(e.target.value)}
          />
        </label>
        <label className="field">
          <span>SPORT</span>
          <select
            value={sportKey}
            onChange={(e) => setSportKey(e.target.value)}
          >
            <option value="">All sports</option>
            {sports.map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <div className="ev-odds-range">
          <label className="field">
            <span>MIN ODDS</span>
            <input
              inputMode="numeric"
              placeholder="-200"
              value={minOdds}
              maxLength={6}
              onChange={(e) => setMinOdds(e.target.value.trim())}
            />
          </label>
          <label className="field">
            <span>MAX ODDS</span>
            <input
              inputMode="numeric"
              placeholder="+300"
              value={maxOdds}
              maxLength={6}
              onChange={(e) =>
                setMaxOdds(e.target.value.trim().replace(/^\+/, ""))
              }
            />
          </label>
        </div>
        <fieldset className="ev-books">
          <legend>
            MY SPORTSBOOKS{" "}
            <button
              type="button"
              className="link-button"
              onClick={() => setOffBooks(new Set())}
            >
              all
            </button>{" "}
            <button
              type="button"
              className="link-button"
              onClick={() => setOffBooks(new Set(books.map(([id]) => id)))}
            >
              none
            </button>
          </legend>
          {books.map(([id, label]) => (
            <label key={id}>
              <input
                type="checkbox"
                checked={!offBooks.has(id)}
                onChange={() =>
                  setOffBooks((prev) => {
                    const next = new Set(prev);
                    if (!next.delete(id)) next.add(id);
                    return next;
                  })
                }
              />
              {label}
            </label>
          ))}
          {books.length === 0 && <small>No books yet.</small>}
        </fieldset>
      </aside>
      <div className="ev-main">
        <div className="ev-count">
          <SlipToggle
            count={slip.length}
            onClick={() => setSlipOpen((o) => !o)}
          />
          <strong>{visible.length}</strong> of {all.length} bets · prices as of{" "}
          {date(data.meta.captured_at)}
          <label className="ev-sort">
            Sort by{" "}
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
        </div>
        {slipOpen && <SlipLog slip={slip} onCleared={refreshSlip} />}
        <div role="table" aria-label="Positive EV bets" className="ev-grid">
          <div role="row" className="ev-head">
            <span role="columnheader">EV</span>
            <span role="columnheader">Event</span>
            <span role="columnheader">Market &amp; line</span>
            <span role="columnheader">Soft book</span>
            <span role="columnheader">Win chance &amp; fair odds</span>
            <span role="columnheader">Scanned</span>
          </div>
          {visible.length === 0 ? (
            <div className="empty-state">
              <h3>No +EV bets right now</h3>
              <p>
                Lower the minimum EV, re-enable books, or press Refresh odds.
                Bets need at least two sharp books pricing the same line.
              </p>
            </div>
          ) : (
            <div
              ref={viewport}
              className="ev-viewport"
              style={{ height: Math.min(viewHeight, visible.length * height) }}
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
                    selected={vm.id === selected}
                    flash={flashes.get(vm.id)}
                    onSelect={select}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
      {active && (
        <div className="kelly-backdrop" onClick={() => setSelected(null)} />
      )}
      <KellyWidget
        vm={active}
        bankroll={bankroll}
        setBankroll={setBankroll}
        multiplier={multiplier}
        setMultiplier={setMultiplier}
        onClose={() => setSelected(null)}
        onLogged={refreshSlip}
      />
    </section>
  );
}

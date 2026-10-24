"use client";
import { useFeedLayout } from "./use-feed-layout";
import { Icon } from "./icon";
import { Countdown } from "./countdown";
export { Countdown } from "./countdown";
import { PlacedProvider, PlacedBadge, PlacedNote, usePlaced } from "./placed";
import { FeedFilters } from "./feed-filters";
import { useDialogFocus } from "./use-dialog-focus";
import { netBackOdds } from "../lib/pricing";
import { savedTimeFilter } from "../lib/feed-time";
import { feedBooks } from "../lib/bookmakers";
import { FeedTimeFilter, useFeedTimeFilter } from "./feed-time-filter";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  MARKETS,
  american,
  date,
  selection,
  sport,
  usd,
} from "../../frontend/format.mjs";
import { choice, list, sorted, text } from "../lib/settings-fields";
import { userStorage } from "../lib/user-storage";
import { loadToolSnapshot } from "../lib/tool-snapshot";
import type {
  Capabilities,
  Game,
  Meta,
  Quote,
  ToolRow,
} from "../lib/contracts";
import { Age, CopyButton, Menu, shortBook } from "./feed-controls";
import { quoteRef, type NewBet } from "../lib/slip";
import type { RefValue } from "../lib/tracker-api";
import { LogBetButton, SlipLog, SlipToggle, useSlip } from "./bet-slip";
import { FeedChangeNote, useFeedChanges } from "./feed-updates";
import { LegLinks } from "./bet-link";
import type { QuoteLinks } from "../lib/bet-links";
import { SettingsBar, useToolSettings } from "./tool-settings";
import { Matchup } from "./media";
import { ErrorCard, Loading } from "./feedback";

type MidRow = Extract<ToolRow, { kind: "middle" }>;
type Data = { caps: Capabilities; games: Game[]; quotes: Quote[]; meta: Meta };
type SortKey = "ratio" | "best" | "miss" | "window" | "time" | "scanned";
interface LegVm {
  netDecimalOdds: string;
  quoteId: string;
  bookId: string;
  bookLabel: string;
  label: string;
  odds: string;
  stake: number;
  ref: Record<string, RefValue>;
  links: QuoteLinks | null;
}
interface Vm {
  id: string;
  matchup: string;
  league: string;
  startsAt: string;
  sportKey: string;
  marketKey: string;
  market: string;
  legs: LegVm[];
  capital: number;
  best: number;
  worst: number;
  window: string;
  width: number;
  states: [string, number][];
  sig: string;
  observedAt: string;
}

const ROW_HEIGHT = { wide: 116, compact: 236 };
const OVERSCAN = 6;
const SETTINGS_KEY = "corner.middle-settings";
const STAKE_PATTERN = /^\d{1,9}(\.\d{1,2})?$/;
type MiddleSettings = {
  timeFilter: string;
  offBooks: string[];
  offSports: string[];
  offMarkets: string[];
  maxMiss: string;
  minWindow: string;
  sortKey: string;
  stake: string;
};
const MIDDLE_DEFAULTS: MiddleSettings = {
  timeFilter: "default",
  offBooks: [],
  offSports: [],
  offMarkets: [],
  maxMiss: "",
  minWindow: "",
  sortKey: "ratio",
  stake: "100",
};
const MISS_PATTERN = /^\d{1,3}$/;
const WINDOW_PATTERN = /^\d{1,4}(\.\d{1,2})?$/;
const MARKET_NAMES = MARKETS as Record<string, string>;

const money = (n: number) => usd(n.toFixed(2));
const pct = (n: number) =>
  `${n > 0 ? "+" : n < 0 ? "-" : ""}${Math.abs(n * 100).toFixed(1)}%`;

const stateLabel = (id: string) =>
  id === "common_refund"
    ? "Push / refund"
    : id
        .replace("score:", "")
        .replace("-inf:", "≤ ")
        .replace(":+inf", " or more")
        .replaceAll(":", "–");

function toVm(
  row: MidRow,
  quotes: Map<string, Quote>,
  games: Map<string, Game>,
  books: Map<string, string>,
): Vm | null {
  const capital = Number(row.capital_required);
  if (row.minimum_profit == null || !(capital > 0)) return null;
  const legs: LegVm[] = [];
  for (const leg of row.calculation.legs) {
    const q = quotes.get(leg.quote_id);
    if (!q) return null;
    legs.push({
      quoteId: leg.quote_id,
      bookId: q.sportsbook_id,
      bookLabel: shortBook(books.get(q.sportsbook_id) ?? q.sportsbook_id),
      label: selection(q),
      odds: american(q.decimal_odds),
      netDecimalOdds: netBackOdds(q.decimal_odds, q.commission_rate),
      stake: Number(leg.stake),
      ref: quoteRef(q),
      links: q.links ?? null,
    });
  }
  const ranges = row.calculation.double_win_ranges;
  const width = ranges.reduce(
    (sum, [a, b]) =>
      sum + (a == null || b == null ? 1e9 : Number(b) - Number(a)),
    0,
  );
  const g = games.get(row.game_id);
  return {
    id: row.id,
    matchup: g?.name ?? "Event",
    league: g?.competition ?? sport(g?.sport_key ?? ""),
    startsAt: g?.starts_at ?? "",
    sportKey: g?.sport_key ?? "",
    marketKey: row.market_key,
    market: MARKET_NAMES[row.market_key] ?? row.market_key,
    legs,
    capital,
    best: Number(row.calculation.payoff.maximum_modeled_profit),
    worst: Number(row.minimum_profit),
    window: ranges.map(([a, b]) => `${a ?? "−∞"}–${b ?? "∞"}`).join(", "),
    width,
    states: row.calculation.payoff.states.map((s): [string, number] => [
      stateLabel(s.state_id),
      Number(s.net_profit),
    ]),
    sig: legs.map((l) => `${l.quoteId}@${l.odds}@${l.label}`).join("|"),
    observedAt: row.oldest_observed_at,
  };
}

// Reward per dollar lost on a miss; free middles sort first.
const reward = (v: Vm) => (v.worst >= 0 ? Infinity : v.best / -v.worst);

const SORTS: Record<SortKey, (a: Vm, b: Vm) => number> = {
  ratio: (a, b) => {
    const x = reward(a);
    const y = reward(b);
    return x === y ? b.best - a.best : y - x;
  },
  best: (a, b) => b.best / b.capital - a.best / a.capital,
  miss: (a, b) => b.worst / b.capital - a.worst / a.capital,
  window: (a, b) => b.width - a.width,
  time: (a, b) =>
    (a.startsAt ? new Date(a.startsAt).getTime() : Infinity) -
    (b.startsAt ? new Date(b.startsAt).getTime() : Infinity),
  scanned: (a, b) => b.observedAt.localeCompare(a.observedAt),
};

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
    const exposure = usePlaced(vm.legs);
    return (
      <div
        role="row"
        data-row-id={vm.id}
        tabIndex={0}
        aria-selected={selected}
        className={`ev-row mid-row ${selected ? "selected" : ""}`}
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
          <span className="ev-badge arb-badge">
            {pct(vm.best / vm.capital)}
          </span>
          <PlacedBadge state={exposure} />
          <small className="mid-loss">Miss {pct(vm.worst / vm.capital)}</small>
        </div>
        <div role="cell" className="ev-cell ev-event">
          <span className="ev-league">
            {vm.league} · {vm.market}
          </span>
          <Matchup text={vm.matchup} sportKey={vm.sportKey} />
          <small>
            {vm.startsAt ? date(vm.startsAt) : ""} ·{" "}
            <Countdown value={vm.startsAt} />
          </small>
          <small className="mid-window">Win both if {vm.window}</small>
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
    a.vm.best === b.vm.best &&
    a.vm.worst === b.vm.worst &&
    a.vm.observedAt === b.vm.observedAt &&
    a.top === b.top &&
    a.selected === b.selected,
);

function Calculator({
  vm,
  shift,
  onAccept,
  stake,
  setStake,
  onClose,
  onLogged,
}: {
  vm: Vm | null;
  shift: "ok" | "moved" | "dropped";
  onAccept: () => void;
  stake: string;
  setStake: (v: string) => void;
  onClose: () => void;
  onLogged: () => void;
}) {
  const validStake = STAKE_PATTERN.test(stake) && Number(stake) > 0;
  const total = validStake ? Number(stake) : 0;
  // The calculator is a drawer, so Escape closes it.
  useEffect(() => {
    if (!vm) return;
    const close = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [vm, onClose]);
  const sig = vm?.sig ?? "";
  // Recalculate only for this row's own prices or the typed stake.
  const scaled = useMemo(() => {
    if (!vm || !total) return null;
    const k = total / vm.capital;
    return {
      stakes: vm.legs.map((l) => l.stake * k),
      best: vm.best * k,
      worst: vm.worst * k,
      states: vm.states.map(([label, v]): [string, number] => [label, v * k]),
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig, total]);

  const logLegs: NewBet[] =
    vm && scaled
      ? vm.legs.map((l, i) => ({
          matchup: vm.matchup,
          line: l.label,
          book: l.bookLabel,
          odds: l.odds,
          decimalOdds: l.netDecimalOdds,
          notes:
            "Net modeled odds after any commission; confirm actual book settlement.",
          stake: scaled.stakes[i].toFixed(2),
          strategy: "middle" as const,
          sportKey: vm.sportKey,
          startsAt: vm.startsAt,
          market: vm.market,
          ref: l.ref,
        }))
      : [];

  const exposure = usePlaced(vm ? vm.legs : []);
  const dialogRef = useDialogFocus(Boolean(vm));
  return (
    <aside
      ref={dialogRef}
      role="dialog"
      aria-modal={vm ? true : undefined}
      aria-hidden={!vm}
      className={`kelly-panel arb-calc ${vm ? "open" : ""}`}
      aria-label="Middle calculator"
    >
      <button className="kelly-close" onClick={onClose} aria-label="Close">
        <Icon name="close" />
      </button>
      <h3>Middle calculator</h3>
      {!vm ? (
        <p className="kelly-empty">Select a middle to size the stakes.</p>
      ) : (
        <>
          {shift !== "ok" && (
            <div role="alert" className="arb-alert">
              <strong>
                {shift === "dropped"
                  ? "This middle is no longer available."
                  : "The line has shifted."}
              </strong>
              <span>
                {shift === "dropped"
                  ? "A sportsbook changed or dropped a price after the latest refresh. The numbers below are the old prices."
                  : "A sportsbook changed its line or odds after the latest refresh."}
              </span>
              {shift === "moved" && (
                <button className="button secondary" onClick={onAccept}>
                  Use the updated prices
                </button>
              )}
            </div>
          )}
          <div className="kelly-head">
            <Matchup text={vm.matchup} sportKey={vm.sportKey} size={22} />
            <span>
              {vm.league} · {vm.market}
            </span>
            <span>Win both if the result lands in {vm.window}</span>
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
          {!validStake || !scaled ? (
            <p className="kelly-empty">Enter a stake greater than zero.</p>
          ) : (
            <>
              {vm.legs.map((l, i) => (
                <div className="arb-stake" key={l.quoteId}>
                  <span>
                    Leg {String.fromCharCode(65 + i)} · {l.bookLabel} {l.label}{" "}
                    @ {l.odds}
                  </span>
                  <output>{money(scaled.stakes[i])}</output>
                  <CopyButton
                    value={scaled.stakes[i].toFixed(2)}
                    label={`leg ${String.fromCharCode(65 + i)}`}
                  />
                </div>
              ))}
              <div className="arb-summary">
                <span>If it lands in the window</span>
                <b className="arb-net">{money(scaled.best)}</b>
                <span>If it misses</span>
                <b className={scaled.worst < 0 ? "mid-loss" : ""}>
                  {money(scaled.worst)}
                </b>
                <span>Total risked</span>
                <b>{money(total)}</b>
              </div>
              <table className="mid-states">
                <caption>Net profit by final margin or total</caption>
                <tbody>
                  {scaled.states.map(([label, v]) => (
                    <tr key={label}>
                      <td>{label}</td>
                      <td className={v < 0 ? "mid-loss" : ""}>{money(v)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          <small className="kelly-note">
            A middle wins big only if the result lands between the two lines.
            Win probability is not estimated.
          </small>
          <LegLinks
            legs={vm.legs.map((l, i) => ({
              links: l.links,
              bookLabel: l.bookLabel,
              label: l.label,
              stake: scaled ? scaled.stakes[i].toFixed(2) : undefined,
            }))}
            startsAt={vm.startsAt}
            unavailable={shift === "dropped"}
          />
          <PlacedNote state={exposure} />
          <LogBetButton
            legs={validStake ? logLegs : []}
            resetKey={`${vm.id}|${vm.sig}|${stake}`}
            onLogged={onLogged}
          />
        </>
      )}
    </aside>
  );
}

export default function MiddleFeed({
  data,
  liveRows,
}: {
  data: Data;
  liveRows?: ToolRow[];
}) {
  const { timeFilter, setTimeFilter, matchesTime } = useFeedTimeFilter(
    liveRows !== undefined,
  );
  const [rows, setRows] = useState<MidRow[] | null>(null);
  const [loadedQuotes, setLoadedQuotes] = useState<Quote[] | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [offBooks, setOffBooks] = useState<Set<string>>(new Set());
  const [offSports, setOffSports] = useState<Set<string>>(new Set());
  const [offMarkets, setOffMarkets] = useState<Set<string>>(new Set());
  const [maxMiss, setMaxMiss] = useState("");
  const [minWindow, setMinWindow] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("ratio");
  const [stake, setStake] = useState("100");
  const [selected, setSelected] = useState<Vm | null>(null);
  const {
    slip,
    open: slipOpen,
    setOpen: setSlipOpen,
    refresh: refreshSlip,
  } = useSlip();

  const settings = useToolSettings<MiddleSettings>({
    tool: "middle",
    defaults: MIDDLE_DEFAULTS,
    snapshot: {
      timeFilter,
      offBooks: sorted(offBooks),
      offSports: sorted(offSports),
      offMarkets: sorted(offMarkets),
      maxMiss,
      minWindow,
      sortKey,
      stake,
    },
    apply: (s) => {
      setTimeFilter(savedTimeFilter(s.timeFilter));
      setOffBooks(new Set(list(s.offBooks)));
      setOffSports(new Set(list(s.offSports)));
      setOffMarkets(new Set(list(s.offMarkets)));
      setMaxMiss(text(s.maxMiss, /^(\d{1,3})?$/, ""));
      setMinWindow(text(s.minWindow, /^(\d{1,4}(\.\d{1,2})?)?$/, ""));
      setSortKey(choice(s.sortKey, Object.keys(SORTS) as SortKey[], "ratio"));
      setStake(text(s.stake, STAKE_PATTERN, MIDDLE_DEFAULTS.stake));
    },
    legacy: () => {
      const saved = JSON.parse(userStorage.getItem(SETTINGS_KEY) ?? "null");
      userStorage.removeItem(SETTINGS_KEY);
      return saved;
    },
  });
  useEffect(() => {
    if (liveRows !== undefined) {
      setError("");
      setRows(liveRows.filter((r): r is MidRow => r.kind === "middle"));
      return;
    }
    const controller = new AbortController();
    setError("");
    loadToolSnapshot("middle", data.meta.snapshot_id, controller.signal)
      .then((bundle) => {
        if (controller.signal.aborted) return;
        setLoadedQuotes(bundle.quotes);
        const items = bundle.rows;
        if (!controller.signal.aborted)
          setRows(items.filter((r): r is MidRow => r.kind === "middle"));
      })
      .catch((e) => {
        if (!controller.signal.aborted)
          setError(e instanceof Error ? e.message : "Request failed.");
      });
    return () => controller.abort();
  }, [data, retry, liveRows]);

  const maps = useMemo(
    () => ({
      quotes: new Map(
        (liveRows !== undefined ? data.quotes : (loadedQuotes ?? [])).map(
          (q) => [q.id, q],
        ),
      ),
      games: new Map(data.games.map((g) => [g.id, g])),
      books: new Map(feedBooks(data.caps.books).map((b) => [b.id, b.name])),
    }),
    [data, loadedQuotes, liveRows],
  );
  const all = useMemo(
    () =>
      (rows ?? [])
        .map((r) => toVm(r, maps.quotes, maps.games, maps.books))
        .filter((v): v is Vm => v !== null),
    [rows, maps],
  );
  const byId = useMemo(() => new Map(all.map((v) => [v.id, v])), [all]);
  const rowIds = useMemo(() => rows?.map((r) => r.id) ?? null, [rows]);
  const change = useFeedChanges(rowIds);
  const bookItems = useMemo(
    () =>
      feedBooks(data.caps.books)
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
  const marketItems = useMemo((): [string, string][] => {
    const m = new Map<string, string>();
    for (const v of all) m.set(v.marketKey, v.market);
    return [...m].sort((a, b) => a[1].localeCompare(b[1]));
  }, [all]);

  const missLimit = MISS_PATTERN.test(maxMiss) ? Number(maxMiss) / 100 : null;
  const widthLimit = WINDOW_PATTERN.test(minWindow) ? Number(minWindow) : null;
  const visible = useMemo(
    () =>
      all
        .filter(
          (v) =>
            matchesTime(v.startsAt) &&
            !offSports.has(v.sportKey) &&
            !offMarkets.has(v.marketKey) &&
            v.legs.every((l) => !offBooks.has(l.bookId)) &&
            (missLimit === null || -v.worst / v.capital <= missLimit) &&
            (widthLimit === null || v.width >= widthLimit),
        )
        .sort(SORTS[sortKey]),
    [
      matchesTime,
      all,
      offBooks,
      offSports,
      offMarkets,
      missLimit,
      widthLimit,
      sortKey,
    ],
  );

  const finite = visible.filter((v) => v.width < 1e9);
  const avgWidth = finite.length
    ? finite.reduce((s, v) => s + v.width, 0) / finite.length
    : null;
  const bestPayoff = visible.length
    ? Math.max(...visible.map((v) => v.best / v.capital))
    : null;

  const [compact, setCompact] = useState(false);
  useEffect(() => {
    const media = matchMedia("(max-width:1100px)");
    const change = () => setCompact(media.matches);
    change();
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, []);
  const height = compact ? ROW_HEIGHT.compact : ROW_HEIGHT.wide;
  const viewport = useRef<HTMLDivElement>(null);
  const [scroll, setScroll] = useState(0);
  useEffect(() => {
    setScroll(0);
    if (viewport.current) viewport.current.scrollTop = 0;
  }, [timeFilter]);
  const frame = useRef(0);
  const onScroll = useCallback(() => {
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() =>
      setScroll(viewport.current?.scrollTop ?? 0),
    );
  }, []);
  useEffect(() => () => cancelAnimationFrame(frame.current), []);
  const viewHeight = 680;
  const { first, last, offsets, total } = useFeedLayout(
    visible,
    compact,
    viewport,
    height,
    scroll,
    viewHeight,
    OVERSCAN,
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
  if (!rows) return <Loading text="Scanning for middles…" />;

  return (
    <PlacedProvider slip={slip}>
      <section className="arb-layout" aria-label="Middles feed">
        <FeedFilters active={!settings.atDefaults}>
          <SettingsBar controls={settings} />
          {liveRows === undefined && (
            <FeedTimeFilter value={timeFilter} onChange={setTimeFilter} />
          )}
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
          <Menu
            title="Markets"
            items={marketItems}
            off={offMarkets}
            setOff={setOffMarkets}
          />
          <label className="field mid-small">
            <span>MAX MISS COST %</span>
            <input
              inputMode="numeric"
              placeholder="any"
              value={maxMiss}
              maxLength={3}
              aria-invalid={maxMiss !== "" && missLimit === null}
              onChange={(e) => setMaxMiss(e.target.value.trim())}
            />
          </label>
          <label className="field mid-small">
            <span>MIN WINDOW (PTS)</span>
            <input
              inputMode="decimal"
              placeholder="any"
              value={minWindow}
              maxLength={7}
              aria-invalid={minWindow !== "" && widthLimit === null}
              onChange={(e) => setMinWindow(e.target.value.trim())}
            />
          </label>
          <label className="field mid-small">
            <span>SORT</span>
            <select
              value={sortKey}
              onChange={(e) => setSortKey(e.target.value as SortKey)}
            >
              <option value="ratio">Best reward vs. miss</option>
              <option value="best">Biggest payoff</option>
              <option value="miss">Smallest miss cost</option>
              <option value="window">Widest window</option>
              <option value="time">Event time (soonest)</option>
              <option value="scanned">Newest scan</option>
            </select>
          </label>
          <span className="arb-status" role="status">
            <i className="arb-pulse" aria-hidden="true" />
            Prices as of{" "}
            {data.meta.captured_at === "1970-01-01T00:00:00Z"
              ? "—"
              : date(data.meta.captured_at)}
          </span>
        </FeedFilters>
        <div className="mid-metrics" aria-label="Middle summary">
          <div>
            <span>MIDDLES FOUND</span>
            <b>{visible.length}</b>
          </div>
          <div>
            <span>AVG. WINDOW (PTS)</span>
            <b>{avgWidth === null ? "—" : avgWidth.toFixed(1)}</b>
          </div>
          <div>
            <span>BEST PAYOFF</span>
            <b className="arb-net">
              {bestPayoff === null ? "—" : pct(bestPayoff)}
            </b>
          </div>
        </div>
        <div className="arb-body">
          <div className="ev-main">
            <div className="ev-count">
              <SlipToggle
                count={slip.length}
                onClick={() => setSlipOpen((o) => !o)}
              />
              <strong>{visible.length}</strong> of {all.length} middles · green
              is the payoff in the window, red is what a miss costs
              <FeedChangeNote change={change} />
            </div>
            {slipOpen && <SlipLog slip={slip} onCleared={refreshSlip} />}
            <div
              role="table"
              aria-label="Middle opportunities"
              className="ev-grid arb-grid"
            >
              <div role="row" className="ev-head">
                <span role="columnheader">Payoff</span>
                <span role="columnheader">Event &amp; window</span>
                <span role="columnheader">Legs</span>
                <span role="columnheader">Scanned</span>
              </div>
              {visible.length === 0 ? (
                <div className="empty-state">
                  <h3>No middles match</h3>
                </div>
              ) : (
                <div
                  ref={viewport}
                  className="ev-viewport"
                  style={{
                    height: Math.min(viewHeight, total),
                  }}
                  onScroll={onScroll}
                >
                  <div
                    className="ev-spacer"
                    role="rowgroup"
                    style={{ height: total }}
                  >
                    {visible.slice(first, last).map((vm, i) => (
                      <Row
                        key={vm.id}
                        vm={vm}
                        top={offsets[first + i]}
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
            onLogged={refreshSlip}
          />
        </div>
      </section>
    </PlacedProvider>
  );
}

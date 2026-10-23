"use client";
import { KellyWidget, SIZING_DEFAULTS, legacySizing } from "./kelly-widget";
export {
  KellyWidget,
  kelly,
  SIZING_DEFAULTS,
  legacySizing,
  BANKROLL_KEY,
  MULTIPLIER_KEY,
} from "./kelly-widget";
import type { SizingSettings } from "./kelly-widget";
export type { KellyVm, SizingSettings } from "./kelly-widget";
import { useFeedLayout } from "./use-feed-layout";
import { Icon } from "./icon";
import { DevigSelector } from "./devig-comparison";
import { fairOddsRange } from "../lib/fair-odds-filter";
import { savedWinChance, passesWinChance } from "../lib/reference-filters";
import { QuoteAge } from "./quote-age";
import { useDialogFocus } from "./use-dialog-focus";
import { netBackOdds } from "../lib/pricing";
import { ParlayToolbar, useParlay } from "./parlay-builder";
import { Menu } from "./feed-controls";
import { builderLeg } from "../lib/parlay";
import { RangeFilter } from "./range-filter";
import { FeedFilters } from "./feed-filters";
import { EvFilterLimits } from "./ev-filter-limits";
import {
  LIMIT_PATTERN,
  matchesEvLimits,
  widestMarket,
} from "../lib/ev-filters";
import { savedTimeFilter } from "../lib/feed-time";
import { feedBooks } from "../lib/bookmakers";
import { FeedTimeFilter, useFeedTimeFilter } from "./feed-time-filter";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  MARKETS,
  american,
  compareDecimal,
  date,
  divDecimal,
  fixed,
  mulDecimal,
  percent,
  selection,
  shiftDecimal,
  sport,
  subDecimal,
  usd,
  ageLabel,
} from "../../frontend/format.mjs";
import type { QuoteLinks } from "../lib/bet-links";
import { choice, list, sorted, text } from "../lib/settings-fields";
import { userStorage } from "../lib/user-storage";
import { sharedPages } from "../lib/api";
import type {
  Capabilities,
  Game,
  Meta,
  Quote,
  ToolRow,
} from "../lib/contracts";
import { quoteRef, type NewBet } from "../lib/slip";
import type { RefValue, Strategy } from "../lib/tracker-api";
import { bookCode, bookLabel, dollars } from "../lib/tracker-math";
import { LogBetButton, useSlip, useTrackedBankroll } from "./bet-slip";
import { FeedChangeNote, useFeedChanges, useOpenBet } from "./feed-updates";
import { Avatar, Matchup } from "./media";
import { BetLinkButton } from "./bet-link";
import { PlacedChip, PlacedNoteFor, PlacedProvider, usePlaced } from "./placed";
import { SettingsBar, useToolSettings } from "./tool-settings";
import { ErrorCard, Loading } from "./feedback";

type EvRow = Extract<ToolRow, { kind: "positive_ev" }>;
type Flash = "up" | "down";
interface Vm {
  sourceIds?: Quote["source_ids"];
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
  excludesDraw?: boolean;
  marketWidth: number | null;
  ev: string;
  decimalOdds: string;
  netDecimalOdds?: string;
  odds: string;
  fairOdds: string | null;
  prob: number;
  startMs: number;
  sharps: string;
  observedAt: string;
  fairProb: string;
  ref: Record<string, RefValue>;
  links: QuoteLinks | null;
}
type Data = { caps: Capabilities; games: Game[]; quotes: Quote[]; meta: Meta };

const ROW_HEIGHT = { wide: 88, compact: 184 };
const OVERSCAN = 6;
const SHARP_BOOKS = new Set([
  "pinnacle",
  "betfair_ex_uk",
  "prophetx",
  "kalshi",
]);
type EvSettings = {
  devigMethod: string;
  minWinChance: string;
  timeFilter: string;
  offBooks: string[];
  minEv: string;
  maxEv: string;
  maxWidth: string;
  sortKey: string;
  minOdds: string;
  maxOdds: string;
  sportKey: string;
};
const EV_DEFAULTS: EvSettings = {
  devigMethod: "current",
  minWinChance: "0",
  timeFilter: "default",
  offBooks: [],
  minEv: "0",
  maxEv: "",
  maxWidth: "",
  sortKey: "ev",
  minOdds: "",
  maxOdds: "",
  sportKey: "",
};
const SETTINGS_KEY = "corner.ev-settings";

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
    excludesDraw: q.market_key === "draw_no_bet",
    marketWidth: widestMarket(
      row.calculation.reference_books.map((b) =>
        b.quote_ids.map((id) => quotes.get(id)?.decimal_odds ?? ""),
      ),
    ),
    ev: row.conditional_ev_ratio,
    netDecimalOdds: q.market_key.endsWith("_lay")
      ? undefined
      : netBackOdds(q.decimal_odds, q.commission_rate),
    decimalOdds: q.decimal_odds,
    odds: american(q.decimal_odds),
    fairOdds: fairAmerican(row.calculation.conditional_fair_probability),
    prob: q.market_key.endsWith("_lay")
      ? 1 - Number(row.calculation.conditional_fair_probability)
      : Number(row.calculation.conditional_fair_probability),
    startMs: g?.starts_at ? new Date(g.starts_at).getTime() : Infinity,
    sharps,
    observedAt: row.oldest_observed_at,
    fairProb: row.calculation.conditional_fair_probability,
    ref: quoteRef(q),
    links: q.links ?? null,
    sourceIds: q.source_ids,
  };
}

// Fractional Kelly on a back bet, uncapped. Lay bets get no suggestion.
function Age({ value }: { value: string }) {
  return <QuoteAge value={value} />;
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
    height,
    selected,
    flash,
    parlaySelected,
    onSelect,
  }: {
    vm: Vm;
    top: number;
    height: number;
    selected: boolean;
    parlaySelected?: boolean;
    flash?: { odds?: Flash; ev?: Flash; tick: number };
    onSelect: (id: string) => void;
  }) {
    return (
      <div
        role="row"
        data-row-id={vm.id}
        tabIndex={0}
        aria-selected={parlaySelected ?? selected}
        className={`ev-row ev-tall ${selected ? "selected" : ""} ${parlaySelected ? "parlay-selected" : ""}`}
        style={{ transform: `translateY(${top}px)`, height }}
        onClick={() => onSelect(vm.id)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onSelect(vm.id);
          }
        }}
      >
        <div role="cell" className="ev-cell ev-edge">
          {parlaySelected && (
            <span className="parlay-check" aria-label="Added to parlay">
              <Icon name="check" />
            </span>
          )}
          <span
            key={`ev-${flash?.tick ?? 0}`}
            className={`ev-badge ${flash?.ev ? `flash-${flash.ev}` : ""}`}
          >
            {percent(vm.ev, true)}
          </span>
          <PlacedChip leg={vm} />
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
            <BetLinkButton
              compact
              links={vm.links}
              bookLabel={vm.bookLabel}
              startsAt={vm.startsAt}
            />
          </span>
        </div>
        <div role="cell" className="ev-cell ev-sharp">
          <strong>{chance(vm.prob)} chance</strong>
          {vm.excludesDraw && (
            <small>Excluding draws; draw refunds stake</small>
          )}
          <small>Fair {vm.fairOdds ?? "—"}</small>
          <small>{vm.sharps}</small>
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
    a.height === b.height &&
    a.selected === b.selected &&
    a.parlaySelected === b.parlaySelected &&
    a.onSelect === b.onSelect &&
    a.flash?.tick === b.flash?.tick,
);

export default function EvFeed({
  data,
  liveRows,
  liveMethod,
  onLiveMethod,
}: {
  data: Data;
  liveRows?: ToolRow[];
  liveMethod?: string;
  onLiveMethod?: (method: string) => void;
}) {
  const [devigMethod, setDevigMethod] = useState("current");
  const parlayContext = useParlay();
  const parlay = liveRows === undefined ? parlayContext : null;
  useEffect(() => {
    if (parlay?.draft.active) setSelected(null);
  }, [parlay?.draft.active]);
  const { timeFilter, setTimeFilter, matchesTime } = useFeedTimeFilter(
    liveRows !== undefined,
  );
  const [rows, setRows] = useState<EvRow[] | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [offBooks, setOffBooks] = useState<Set<string>>(new Set());
  const [minEv, setMinEv] = useState("0");
  const [minWinChance, setMinWinChance] = useState("0");
  const [pricedSnapshot, setPricedSnapshot] = useState<string | undefined>(
    undefined,
  );
  const [maxEv, setMaxEv] = useState("");
  const [maxWidth, setMaxWidth] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("ev");
  const [minOdds, setMinOdds] = useState("");
  const [maxOdds, setMaxOdds] = useState("");
  const { slip, refresh: refreshSlip } = useSlip();
  const [sportKey, setSportKey] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [bankroll, setBankroll] = useState("1000");
  const [multiplier, setMultiplier] = useState("0.25");
  const [flashes, setFlashes] = useState<
    Map<string, { odds?: Flash; ev?: Flash; tick: number }>
  >(new Map());
  const previous = useRef<Map<string, { odds: string; ev: string }>>(new Map());
  const tickRef = useRef(0);

  const pricingSelection = `${data.meta.snapshot_id}|${devigMethod}`;
  const settings = useToolSettings<EvSettings>({
    tool: "positive_ev",
    defaults: EV_DEFAULTS,
    snapshot: {
      devigMethod,
      minWinChance,
      timeFilter,
      offBooks: sorted(offBooks),
      minEv,
      maxEv,
      maxWidth,
      sortKey,
      minOdds,
      maxOdds,
      sportKey,
    },
    apply: (s) => {
      setDevigMethod(
        choice(
          s.devigMethod,
          [
            "current",
            "multiplicative",
            "additive",
            "power",
            "shin",
            "worst_case",
          ],
          "current",
        ),
      );
      setMinWinChance(savedWinChance(s.minWinChance));
      setTimeFilter(savedTimeFilter(s.timeFilter));
      setOffBooks(new Set(list(s.offBooks)));
      setMinEv(text(s.minEv, /^\d{1,2}(\.\d{1,2})?$/, EV_DEFAULTS.minEv));
      setSortKey(choice(s.sortKey, Object.keys(SORTS) as SortKey[], "ev"));
      setMaxEv(text(s.maxEv, LIMIT_PATTERN, ""));
      setMaxWidth(text(s.maxWidth, LIMIT_PATTERN, ""));
      setMinOdds(text(s.minOdds, /^[+-]?\d{0,5}$/, ""));
      setMaxOdds(text(s.maxOdds, /^[+-]?\d{0,5}$/, ""));
      setSportKey(text(s.sportKey, /^[a-z0-9_]{0,60}$/, ""));
    },
    legacy: () => {
      const saved = JSON.parse(userStorage.getItem(SETTINGS_KEY) ?? "null");
      userStorage.removeItem(SETTINGS_KEY);
      return saved ? { ...saved, offBooks: saved.off } : null;
    },
  });
  // Bankroll and Kelly multiplier belong to the account too, shared with the player props page.
  useToolSettings<SizingSettings>({
    tool: "sizing",
    defaults: SIZING_DEFAULTS,
    snapshot: { bankroll, multiplier },
    apply: (s) => {
      setBankroll(text(s.bankroll, /^[0-9.]{1,13}$/, SIZING_DEFAULTS.bankroll));
      setMultiplier(
        text(s.multiplier, /^(0\.[1-9]\d?|1)$/, SIZING_DEFAULTS.multiplier),
      );
    },
    legacy: legacySizing,
    presets: false,
  });
  useEffect(() => {
    if (liveRows !== undefined) {
      setError("");
      setRows(liveRows.filter((r): r is EvRow => r.kind === "positive_ev"));
      onLiveMethod?.(devigMethod);
      setPricedSnapshot(
        liveMethod === devigMethod ? pricingSelection : undefined,
      );
      return;
    }
    const controller = new AbortController();
    setError("");
    sharedPages<ToolRow>(
      "tools/positive_ev",
      data.meta.snapshot_id,
      controller.signal,
      {
        params: devigMethod === "current" ? {} : { devig_method: devigMethod },
      },
    )
      .then((items) => {
        if (!controller.signal.aborted) {
          setRows(items.filter((r): r is EvRow => r.kind === "positive_ev"));
          setPricedSnapshot(pricingSelection);
        }
      })
      .catch((e) => {
        if (!controller.signal.aborted)
          setError(e instanceof Error ? e.message : "Request failed.");
      });
    return () => controller.abort();
  }, [data, retry, devigMethod, liveRows, liveMethod, onLiveMethod]);

  const maps = useMemo(
    () => ({
      quotes: new Map(data.quotes.map((q) => [q.id, q])),
      games: new Map(data.games.map((g) => [g.id, g])),
      books: new Map(feedBooks(data.caps.books).map((b) => [b.id, b.name])),
    }),
    [data],
  );
  const all = useMemo(
    () =>
      (pricedSnapshot === pricingSelection ? (rows ?? []) : [])
        .map((r) => toVm(r, maps.quotes, maps.games, maps.books))
        .filter((v): v is Vm => v !== null)
        .sort(SORTS.ev),
    [rows, maps, pricedSnapshot, pricingSelection],
  );

  // Flash only the cells whose price or edge moved since the last snapshot.
  const parlayLegs = useMemo(() => all.map((v) => builderLeg(v, "ev")), [all]);
  useEffect(() => {
    if (rows !== null) parlay?.register("ev", parlayLegs);
  }, [parlay?.register, parlayLegs, rows]);
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
    for (const b of feedBooks(data.caps.books))
      list.set(b.id, shortBook(b.name));
    return [...list].sort((a, b) => a[1].localeCompare(b[1]));
  }, [all, data]);
  const sports = useMemo(() => {
    const m = new Map<string, string>();
    for (const v of all) if (v.sportKey) m.set(v.sportKey, v.league);
    return [...m].sort((a, b) => a[1].localeCompare(b[1]));
  }, [all]);
  // A saved league that is not in today's data is ignored rather than hiding every bet.
  const sportFilter = sports.some(([key]) => key === sportKey) ? sportKey : "";
  const minRatio = shiftDecimal(minEv, -2);
  const fairRange = useMemo(
    () => fairOddsRange(minOdds, maxOdds),
    [minOdds, maxOdds],
  );
  const visible = useMemo(
    () =>
      all
        .filter(
          (v) =>
            passesWinChance(v.prob, minWinChance) &&
            matchesTime(v.startsAt) &&
            (parlay?.draft.active
              ? v.bookId === parlay.draft.book && !v.lay
              : !offBooks.has(v.bookId)) &&
            (!sportFilter || v.sportKey === sportFilter) &&
            compareDecimal(v.ev, minRatio) >= 0 &&
            matchesEvLimits(v.ev, v.marketWidth, maxEv, maxWidth) &&
            fairRange.test(v.fairProb),
        )
        .sort(SORTS[sortKey]),
    [
      matchesTime,
      minWinChance,
      all,
      offBooks,
      sportFilter,
      minRatio,
      maxEv,
      maxWidth,
      fairRange,
      sortKey,
      parlay?.draft.active,
      parlay?.draft.book,
    ],
  );

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
  const select = useCallback(
    (id: string) => {
      if (parlay?.draft.active) {
        const bet = all.find((v) => v.id === id);
        if (bet) parlay.toggle(builderLeg(bet, "ev"));
      } else setSelected(id);
    },
    [parlay, all],
  );
  const active = visible.find((v) => v.id === selected) ?? null;
  const present = useMemo(
    () => selected !== null && all.some((v) => v.id === selected),
    [all, selected],
  );
  const { shown, unavailable } = useOpenBet(selected, active, present);
  const rowIds = useMemo(() => rows?.map((r) => r.id) ?? null, [rows]);
  const change = useFeedChanges(rowIds);

  if (error)
    return <ErrorCard message={error} retry={() => setRetry((n) => n + 1)} />;
  if (!rows) return <Loading text="Scanning for +EV bets…" />;

  return (
    <PlacedProvider slip={slip}>
      <section className="ev-layout" aria-label="Positive EV feed">
        <FeedFilters active={!settings.atDefaults}>
          <SettingsBar controls={settings} />
          <DevigSelector value={devigMethod} onChange={setDevigMethod} />
          {liveRows === undefined && (
            <div className="ev-filter-actions">
              <ParlayToolbar />
              <FeedTimeFilter value={timeFilter} onChange={setTimeFilter} />
            </div>
          )}
          <RangeFilter
            label="Minimum estimated win chance"
            value={minWinChance}
            onChange={setMinWinChance}
            max={100}
            step={1}
          />
          <RangeFilter
            label="Minimum EV"
            value={minEv}
            onChange={(value) => {
              setMinEv(value);
              if (maxEv && Number(value) > Number(maxEv)) setMaxEv(value);
            }}
          />

          <EvFilterLimits
            maxEv={maxEv}
            maxWidth={maxWidth}
            setMaxEv={(value) => {
              setMaxEv(value);
              if (value && Number(value) < Number(minEv)) setMinEv(value);
            }}
            setMaxWidth={setMaxWidth}
          />
          <label className="field">
            <span>SPORT</span>
            <select
              value={sportFilter}
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
          <div
            className="ev-odds-range"
            title="Filters model fair American odds, not the sportsbook price."
          >
            <label className="field">
              <span>MIN FAIR ODDS</span>
              <input
                inputMode="numeric"
                placeholder="-200"
                value={minOdds}
                maxLength={6}
                onChange={(e) => setMinOdds(e.target.value.trim())}
              />
            </label>
            <label className="field">
              <span>MAX FAIR ODDS</span>
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
            {!fairRange.valid && (
              <small role="alert">
                Enter valid fair American odds, with minimum no higher than
                maximum.
              </small>
            )}
          </div>
          <Menu
            title="Sportsbooks"
            items={books}
            off={offBooks}
            setOff={setOffBooks}
          />
        </FeedFilters>
        <div className="ev-main">
          <div className="ev-count">
            <strong>{visible.length}</strong> of {all.length} bets · prices as
            of{" "}
            {data.meta.captured_at === "1970-01-01T00:00:00Z"
              ? "—"
              : date(data.meta.captured_at)}
            <FeedChangeNote change={change} />
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
          <div role="table" aria-label="Positive EV bets" className="ev-grid">
            <div role="row" className="ev-head">
              <span role="columnheader">EV</span>
              <span role="columnheader">Event</span>
              <span role="columnheader">Market &amp; line</span>
              <span role="columnheader">Sportsbook</span>
              <span role="columnheader">Win chance &amp; fair odds</span>
              <span role="columnheader">Scanned</span>
            </div>
            {visible.length === 0 ? (
              <div className="empty-state">
                <h3>
                  {all.length
                    ? "No bets match your filters"
                    : "No EV bets available yet"}
                </h3>

                {!settings.atDefaults && (
                  <button
                    className="button secondary"
                    type="button"
                    onClick={settings.reset}
                  >
                    Reset filters
                  </button>
                )}
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
                      height={height}
                      selected={vm.id === selected}
                      parlaySelected={
                        parlay?.draft.active
                          ? parlay.selected(builderLeg(vm, "ev").key)
                          : undefined
                      }
                      flash={flashes.get(vm.id)}
                      onSelect={select}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
        {shown && (
          <div className="kelly-backdrop" onClick={() => setSelected(null)} />
        )}
        <KellyWidget
          vm={shown}
          unavailable={unavailable}
          bankroll={bankroll}
          setBankroll={setBankroll}
          multiplier={multiplier}
          setMultiplier={setMultiplier}
          onClose={() => setSelected(null)}
          onLogged={refreshSlip}
        />
      </section>
    </PlacedProvider>
  );
}

"use client";
import { QuoteAge } from "./quote-age";
import { ParlayToolbar, useParlay } from "./parlay-builder";
import { Menu } from "./arb-feed";
import { builderLeg } from "../lib/parlay";
import { restoredFetchMarkets } from "../lib/props-fetch-settings";
import { RangeFilter } from "./range-filter";
import { FeedFilters } from "./feed-filters";
import { EvFilterLimits } from "./ev-filter-limits";
import { LIMIT_PATTERN, matchesEvLimits } from "../lib/ev-filters";
import { passesPropEdge } from "../lib/prop-edge";
import { savedTimeFilter } from "../lib/feed-time";
import { feedBooks, PROP_BOOKS } from "../lib/bookmakers";
import { FeedTimeFilter, useFeedTimeFilter } from "./feed-time-filter";
import { choice, list, sorted, text } from "../lib/settings-fields";
import { userStorage } from "../lib/user-storage";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  american,
  ageLabel,
  compareDecimal,
  date,
  divDecimal,
  percent,
  shiftDecimal,
} from "../../frontend/format.mjs";
import {
  loadProps,
  refreshProps,
  type PropBet,
  type PropsStatus,
} from "../lib/refresh-api";
import {
  KellyWidget,
  SIZING_DEFAULTS,
  legacySizing,
  type KellyVm,
  type SizingSettings,
} from "./ev-feed";
import { BetLinkButton } from "./bet-link";
import { PlacedChip, PlacedProvider } from "./placed";
import { SettingsBar, useToolSettings } from "./tool-settings";
import { useSlip } from "./bet-slip";
import { FeedChangeNote, useFeedChanges, useOpenBet } from "./feed-updates";
import { Avatar, Matchup } from "./media";
import Link from "next/link";
import { labHref } from "../lib/lab";
import { ErrorCard, Loading } from "./workspace";

const BOOK_NAMES: Record<string, string> = {
  draftkings: "DraftKings",
  fanduel: "FanDuel",
  espnbet: "theScore Bet",
  betmgm: "BetMGM",
  novig: "Novig",
  betrivers: "BetRivers",
  pinnacle: "Pinnacle",
  betfair_ex_uk: "Betfair Exchange",
  prophetx: "ProphetX",
  kalshi: "Kalshi",
};
// Only these books are offered as bettable options; sharps feed the fair price only.
const BETTING_BOOKS = [
  "betmgm",
  "betrivers",
  "draftkings",
  "fanduel",
  "novig",
  "espnbet",
];
const bookName = (id: string) =>
  PROP_BOOKS.find((b) => b.id === id)?.name ?? BOOK_NAMES[id] ?? id;
const SETTINGS_KEY = "corner.props-settings";
const credits = (n: number) => `${n} credit${n === 1 ? "" : "s"}`;
const PAGE = 100;

interface Vm extends KellyVm {
  assumedMargin?: string | null;
  stressMargin?: string | null;
  inferredMargin?: boolean;
  sourceIds?: PropBet["source_ids"];
  gameId: string;
  sportKey: string;
  marketKey: string;
  groupName: string;
  player: string;
  startsAt: string;
  startMs: number;
  bookId: string;
  fairOdds: string | null;
  prob: number;
  fair: string;
  marketWidth: number | null;
  sharps: string;
  referenceWeights: string;
  allocationSensitivity: PropBet["allocation_sensitivity"];
  observedAt: string | null;
}

const oddsToDecimal = (v: string) => {
  if (!/^-?\d{2,5}$/.test(v)) return null;
  const n = Number(v);
  if (Math.abs(n) < 100) return null;
  return n > 0 ? 1 + n / 100 : 1 + 100 / -n;
};

function toVm(b: PropBet): Vm {
  let fairOdds: string | null = null;
  try {
    fairOdds = american(divDecimal("1", b.fair_probability));
  } catch {}
  const side =
    b.point == null ? b.side : `${b.side} ${shiftDecimal(b.point, 0)}`;
  return {
    id: b.id,
    gameId: b.event_id,
    sportKey: b.sport_key,
    marketKey: b.market_key,
    groupName: b.group,
    player: b.player,
    matchup: `${b.away} @ ${b.home}`,
    market: b.market_label,
    line: `${b.player} · ${side}`,
    startsAt: b.starts_at,
    startMs: new Date(b.starts_at).getTime(),
    bookId: b.book,
    bookLabel: bookName(b.book),
    lay: false,
    ev: b.ev,
    netDecimalOdds: b.net_decimal_odds,
    decimalOdds: b.price,
    odds: american(b.price),
    fairOdds,
    prob: Number(b.fair_probability),
    fair: b.fair_probability,
    assumedMargin: b.assumed_margin,
    stressMargin: b.stress_margin,
    inferredMargin: b.probability_basis === "observed_margin_transfer",
    marketWidth:
      b.market_width_cents == null ? null : Number(b.market_width_cents),
    sharps: b.sharps.map(bookName).join(" + "),
    referenceWeights: Object.entries(b.reference_weights ?? {})
      .sort((a, b) => Number(b[1]) - Number(a[1]))
      .map(
        ([book, weight]) =>
          `${bookName(book)} ${(Number(weight) * 100).toFixed(1)}%`,
      )
      .join(" · "),
    allocationSensitivity: b.allocation_sensitivity,
    observedAt: b.observed_at,
    strategy: "prop",
    fairProb: b.fair_probability,
    links: b.links ?? null,
    sourceIds: b.source_ids,
    ref: {
      game_id: b.event_id,
      market_key: "prop",
      prop_market: b.market_key,
      player: b.player,
      side: b.side.toLowerCase(),
      point: b.point == null ? null : Number(b.point),
      away: b.away,
      home: b.home,
    },
  };
}

type SortKey =
  | "ev"
  | "chance_high"
  | "chance_low"
  | "time"
  | "odds_high"
  | "odds_low"
  | "player"
  | "scanned";
const SORT_LABELS: [SortKey, string][] = [
  ["ev", "EV % (highest)"],
  ["chance_high", "Win chance (highest)"],
  ["chance_low", "Win chance (longshots)"],
  ["time", "Event time (soonest)"],
  ["odds_high", "Odds (highest payout)"],
  ["odds_low", "Odds (shortest price)"],
  ["player", "Player (A–Z)"],
  ["scanned", "Newest scan"],
];
const SORTS: Record<SortKey, (a: Vm, b: Vm) => number> = {
  ev: (a, b) => compareDecimal(b.ev, a.ev),
  chance_high: (a, b) => b.prob - a.prob,
  chance_low: (a, b) => a.prob - b.prob,
  time: (a, b) => a.startMs - b.startMs,
  odds_high: (a, b) => Number(b.decimalOdds) - Number(a.decimalOdds),
  odds_low: (a, b) => Number(a.decimalOdds) - Number(b.decimalOdds),
  player: (a, b) => a.player.localeCompare(b.player),
  scanned: (a, b) => (b.observedAt ?? "").localeCompare(a.observedAt ?? ""),
};

function Age({ value }: { value: string | null }) {
  return <QuoteAge value={value} />;
}

type PropsSettings = {
  oneSidedMargin: string;
  timeFilter: string;
  fetchSport: string;
  fetchMarkets: string[] | null;
  fetchEvents: number;
  sportKey: string;
  marketKey: string;
  eventId: string;
  search: string;
  minEv: string;
  maxEv: string;
  maxWidth: string;
  minOdds: string;
  maxOdds: string;
  sortKey: string;
  offBooks: string[];
};
const PROPS_DEFAULTS: PropsSettings = {
  oneSidedMargin: "",
  timeFilter: "default",
  fetchSport: "",
  fetchMarkets: null,
  fetchEvents: 8,
  sportKey: "",
  marketKey: "",
  eventId: "",
  search: "",
  minEv: "0",
  maxEv: "",
  maxWidth: "",
  minOdds: "",
  maxOdds: "",
  sortKey: "ev",
  offBooks: [],
};

export default function PropsFeed({ reload }: { reload: number }) {
  const parlay = useParlay();
  useEffect(() => {
    if (parlay?.draft.active) setSelected(null);
  }, [parlay?.draft.active]);
  const { timeFilter, setTimeFilter, matchesTime } = useFeedTimeFilter();
  const [status, setStatus] = useState<PropsStatus | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [sportKey, setSportKey] = useState("");
  const [marketKey, setMarketKey] = useState("");
  const [search, setSearch] = useState("");
  const [eventId, setEventId] = useState("");
  const [minEv, setMinEv] = useState("0");
  const [oneSidedMargin, setOneSidedMargin] = useState("");
  const validOneSidedMargin =
    /^(?:\d|[1-4]\d|50)(?:\.\d{1,2})?$/.test(oneSidedMargin) &&
    Number(oneSidedMargin) <= 50;
  const assumedMarginRatio = validOneSidedMargin
    ? shiftDecimal(oneSidedMargin, -2)
    : undefined;
  const [maxEv, setMaxEv] = useState("");
  const [maxWidth, setMaxWidth] = useState("");
  const [minOdds, setMinOdds] = useState("");
  const [maxOdds, setMaxOdds] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("ev");
  const [offBooks, setOffBooks] = useState<Set<string>>(new Set());
  const [shown, setShown] = useState(PAGE);
  const [selected, setSelected] = useState<string | null>(null);
  const [bankroll, setBankroll] = useState("1000");
  const [multiplier, setMultiplier] = useState("0.25");
  const { slip, refresh: refreshSlip } = useSlip();
  const fetchInitialized = useRef(false);
  const [fetchSport, setFetchSport] = useState("");
  const [fetchMarkets, setFetchMarkets] = useState<string[]>([]);
  const [fetchEvents, setFetchEvents] = useState(8);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ text: string; ok: boolean } | null>(
    null,
  );

  const settings = useToolSettings<PropsSettings>({
    tool: "props",
    defaults: {
      ...PROPS_DEFAULTS,
      fetchSport: status?.sports[0]?.key ?? "",
      fetchMarkets: status
        ? restoredFetchMarkets(
            null,
            status.markets[status.sports[0]?.key ?? ""] ?? [],
          )
        : null,
    },
    snapshot: {
      oneSidedMargin,
      timeFilter,
      fetchSport,
      fetchMarkets: fetchInitialized.current ? fetchMarkets : null,
      fetchEvents,
      sportKey,
      marketKey,
      eventId,
      search,
      minEv,
      maxEv,
      maxWidth,
      minOdds,
      maxOdds,
      sortKey,
      offBooks: sorted(offBooks),
    },
    apply: (s) => {
      const margin = text(s.oneSidedMargin, /^\d{1,2}(\.\d{1,2})?$/, "");
      setOneSidedMargin(Number(margin) <= 50 ? margin : "");
      setTimeFilter(savedTimeFilter(s.timeFilter));
      const fetchKey =
        text(s.fetchSport, /^[a-z0-9_]{0,60}$/, "") ||
        status?.sports[0]?.key ||
        "";
      const fetchCatalog = status?.markets[fetchKey] ?? [];
      fetchInitialized.current =
        Array.isArray(s.fetchMarkets) || fetchCatalog.length > 0;
      setFetchMarkets(
        Array.isArray(s.fetchMarkets)
          ? list(s.fetchMarkets)
          : restoredFetchMarkets(null, fetchCatalog),
      );
      setFetchSport(
        text(s.fetchSport, /^[a-z0-9_]{0,60}$/, "") ||
          status?.sports[0]?.key ||
          "",
      );
      setFetchEvents(
        Number.isInteger(s.fetchEvents) &&
          s.fetchEvents >= 1 &&
          s.fetchEvents <= 20
          ? s.fetchEvents
          : 8,
      );
      setSportKey(text(s.sportKey, /^[a-z0-9_]{0,60}$/, ""));
      setMarketKey(text(s.marketKey, /^[a-z0-9_]{0,60}$/, ""));
      setEventId(text(s.eventId, /^[A-Za-z0-9_-]{0,80}$/, ""));
      setSearch(text(s.search, /^.{0,60}$/, ""));
      setMinEv(text(s.minEv, /^\d{1,2}(\.\d{1,2})?$/, "0"));
      setMaxEv(text(s.maxEv, LIMIT_PATTERN, ""));
      setMaxWidth(text(s.maxWidth, LIMIT_PATTERN, ""));
      setMinOdds(text(s.minOdds, /^-?\d{0,5}$/, ""));
      setMaxOdds(text(s.maxOdds, /^-?\d{0,5}$/, ""));
      setSortKey(choice(s.sortKey, Object.keys(SORTS) as SortKey[], "ev"));
      setOffBooks(new Set(list(s.offBooks)));
    },
    legacy: () => {
      const saved = JSON.parse(userStorage.getItem(SETTINGS_KEY) ?? "null");
      userStorage.removeItem(SETTINGS_KEY);
      return saved ? { ...saved, offBooks: saved.off } : null;
    },
  });
  // Bankroll and Kelly multiplier are shared with the Positive EV page.
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
    const controller = new AbortController();
    setError("");
    loadProps(controller.signal, assumedMarginRatio)
      .then((s) => {
        if (controller.signal.aborted) return;
        setStatus(s);
        setFetchSport((cur) => cur || s.sports[0]?.key || "");
      })
      .catch((e) => {
        if (!controller.signal.aborted)
          setError(e instanceof Error ? e.message : "Request failed.");
      });
    return () => controller.abort();
  }, [retry, reload, assumedMarginRatio]);

  const catalog = status?.markets[fetchSport] ?? [];
  // Reset the picks to the defaults only when the league changes. The status object is
  // replaced after every fetch, which used to wipe the user's chosen markets.
  const catalogKey = catalog.map((m) => m.key).join(",");
  useEffect(() => {
    if (!catalog.length) return;
    if (!fetchInitialized.current) {
      fetchInitialized.current = true;
      setFetchMarkets(catalog.filter((m) => m.default).map((m) => m.key));
    } else {
      setFetchMarkets((current) =>
        current.filter((key) => catalog.some((m) => m.key === key)),
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchSport, catalogKey]);

  const all = useMemo(
    () => (status?.bets ?? []).map(toVm).sort(SORTS.ev),
    [status],
  );
  const parlayLegs = useMemo(
    () => all.map((v) => builderLeg(v, "prop")),
    [all],
  );
  useEffect(() => {
    if (status !== null) parlay?.register("prop", parlayLegs);
  }, [parlay?.register, parlayLegs, status]);
  const select = (v: Vm) =>
    parlay?.draft.active
      ? parlay.toggle(builderLeg(v, "prop"))
      : setSelected(v.id);
  const sports = useMemo(
    () =>
      status
        ? status.sports.filter((s) => all.some((v) => v.sportKey === s.key))
        : [],
    [status, all],
  );
  // A filter whose value no longer exists in the data (its bets were replaced by an update)
  // must not keep hiding everything behind a dropdown that looks like "All".
  const activeSport = sports.some((s) => s.key === sportKey) ? sportKey : "";
  const inSport = useMemo(
    () => all.filter((v) => !activeSport || v.sportKey === activeSport),
    [all, activeSport],
  );
  const markets = useMemo(() => {
    const m = new Map<string, { label: string; group: string }>();
    for (const v of inSport)
      m.set(v.marketKey, { label: v.market, group: v.groupName });
    const groups = new Map<string, [string, string][]>();
    for (const [key, v] of m)
      groups.set(v.group, [...(groups.get(v.group) ?? []), [key, v.label]]);
    return [...groups].sort((a, b) => a[0].localeCompare(b[0]));
  }, [inSport]);
  const events = useMemo(() => {
    const m = new Map<string, Vm>();
    for (const v of inSport) m.set(v.gameId, v);
    return [...m.values()].sort((a, b) => a.startMs - b.startMs);
  }, [inSport]);
  const activeMarket = markets.some(([, items]) =>
    items.some(([key]) => key === marketKey),
  )
    ? marketKey
    : "";
  const activeEvent = events.some((v) => v.gameId === eventId) ? eventId : "";
  const books = useMemo(
    () =>
      [
        ...new Set([
          ...PROP_BOOKS.map((b) => b.id),
          ...all.map((b) => b.bookId),
        ]),
      ].sort((a, b) => bookName(a).localeCompare(bookName(b))),
    [all],
  );

  const minRatio = shiftDecimal(minEv, -2);
  const lo = oddsToDecimal(minOdds);
  const hi = oddsToDecimal(maxOdds);
  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return inSport
      .filter(
        (v) =>
          matchesTime(v.startsAt) &&
          (parlay?.draft.active
            ? v.bookId === parlay.draft.book
            : !offBooks.has(v.bookId)) &&
          (!activeMarket || v.marketKey === activeMarket) &&
          (!activeEvent || v.gameId === activeEvent) &&
          (!needle || v.player.toLowerCase().includes(needle)) &&
          passesPropEdge(v.ev, minRatio) &&
          matchesEvLimits(v.ev, v.marketWidth, maxEv, maxWidth) &&
          (lo === null || Number(v.decimalOdds) >= lo) &&
          (hi === null || Number(v.decimalOdds) <= hi),
      )
      .sort(SORTS[sortKey]);
  }, [
    parlay?.draft.active,
    parlay?.draft.book,
    matchesTime,
    inSport,
    offBooks,
    activeMarket,
    activeEvent,
    search,
    minRatio,
    maxEv,
    maxWidth,
    lo,
    hi,
    sortKey,
  ]);
  useEffect(
    () => setShown(PAGE),
    [
      timeFilter,
      sportKey,
      marketKey,
      eventId,
      search,
      minEv,
      maxEv,
      maxWidth,
      minOdds,
      maxOdds,
      sortKey,
      offBooks,
    ],
  );
  const active = visible.find((v) => v.id === selected) ?? null;
  const present = useMemo(
    () => selected !== null && all.some((v) => v.id === selected),
    [all, selected],
  );
  const { shown: openBet, unavailable } = useOpenBet(selected, active, present);
  const betIds = useMemo(
    () => status?.bets?.map((b) => b.id) ?? null,
    [status?.bets],
  );
  const change = useFeedChanges(betIds);
  const hiddenAsOld =
    !!status?.last_success_at &&
    status.max_age_seconds > 0 &&
    Date.now() - new Date(status.last_success_at).getTime() >
      status.max_age_seconds * 1000;

  const estimate = fetchEvents * fetchMarkets.length * 2;
  const fetchNow = useCallback(async () => {
    if (
      !fetchSport ||
      !fetchMarkets.length ||
      status?.manual_fetch_enabled !== true
    )
      return;
    if (
      !window.confirm(
        `Fetch ${fetchMarkets.length} prop market${fetchMarkets.length === 1 ? "" : "s"} for up to ${fetchEvents} game${fetchEvents === 1 ? "" : "s"}? This uses up to ${credits(estimate)}.`,
      )
    )
      return;
    setBusy(true);
    setNotice(null);
    try {
      const result = await refreshProps(fetchSport, fetchMarkets, fetchEvents);
      setNotice({
        text: result.message ?? "Done.",
        ok: Boolean(result.refreshed) && !result.stopped,
      });
      setRetry((n) => n + 1);
      // Show the fetched league only when it produced bets; otherwise leave the view alone.
      if ((result.bets_found ?? 0) > 0) setSportKey(fetchSport);
    } catch (e) {
      setNotice({
        text: e instanceof Error ? e.message : "Refresh failed.",
        ok: false,
      });
    } finally {
      setBusy(false);
    }
  }, [fetchSport, fetchMarkets, fetchEvents, estimate]);

  if (error)
    return <ErrorCard message={error} retry={() => setRetry((n) => n + 1)} />;
  if (!status) return <Loading text="Scanning player props…" />;

  const groups = new Map<string, typeof catalog>();
  for (const m of catalog)
    groups.set(m.group, [...(groups.get(m.group) ?? []), m]);

  return (
    <PlacedProvider slip={slip}>
      <section className="ev-layout props-layout" aria-label="Player props">
        <details className="feed-guide">
          <summary>One-sided props pricing</summary>
          <p>
            Anytime touchdown (ATD) and anytime goalscorer (ATG) props can be
            priced when two other reference books quote both Yes and No for that
            exact player. A Yes-only list does not reveal the margin: several
            players can score in the same game. Otherwise, one-sided props are
            priced automatically when two other reference books have enough
            complete prices in this event and prop market to estimate their
            margins. Each book needs three other players. Results are labeled as
            modeled; EV uses the larger observed margin as a sensitivity check.
            This is not a calibrated win rate or a confidence bound. Select No
            limit for market width when the opposite price is unavailable.
          </p>
          <p>
            When paired prices and observed margin samples are unavailable,
            automatic mode uses a provisional 10% overround assumption with a
            20% stress scenario. The displayed EV uses the more conservative
            scenario after supported fees. Rows are marked Modeled and appear
            only for a positive estimated edge that meets your minimum EV. These
            percentages are policy assumptions, not fitted margins or guaranteed
            profit.
          </p>
          <label className="field">
            <span>OPTIONAL MARGIN OVERRIDE (%)</span>
            <input
              inputMode="decimal"
              value={oneSidedMargin}
              placeholder="Auto: paired, observed, then 10% / 20% stress"
              maxLength={5}
              onChange={(e) => setOneSidedMargin(e.target.value.trim())}
            />
          </label>
          {oneSidedMargin && !validOneSidedMargin && (
            <p role="alert">Enter a margin from 0 to 50 percent.</p>
          )}
          <p>
            Requires two other books on the exact selection. Fees still apply.
            Integer lines are conditional on no push; pick&apos;em payouts
            require a lineup model.
          </p>
          <p>
            Reference influence is weighted, not equal: FanDuel carries the
            highest current player-prop prior, followed by Pinnacle, then other
            eligible references. These are provisional reputation weights, not
            measured accuracy rankings. Each row shows the weights actually
            used; the offered sportsbook never prices its own bet.
          </p>
        </details>
        <FeedFilters active={!settings.atDefaults}>
          <SettingsBar controls={settings} />
          <div className="ev-filter-actions">
            <ParlayToolbar />
            <FeedTimeFilter value={timeFilter} onChange={setTimeFilter} />
          </div>
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
              value={activeSport}
              onChange={(e) => {
                setSportKey(e.target.value);
                setMarketKey("");
                setEventId("");
              }}
            >
              <option value="">All sports</option>
              {sports.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>PROP MARKET</span>
            <select
              value={activeMarket}
              onChange={(e) => setMarketKey(e.target.value)}
            >
              <option value="">All props</option>
              {markets.map(([group, items]) => (
                <optgroup key={group} label={group}>
                  {items.map(([key, label]) => (
                    <option key={key} value={key}>
                      {label}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </label>
          <label className="field">
            <span>GAME</span>
            <select
              value={activeEvent}
              onChange={(e) => setEventId(e.target.value)}
            >
              <option value="">All games</option>
              {events.map((v) => (
                <option key={v.gameId} value={v.gameId}>
                  {v.matchup}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>PLAYER</span>
            <input
              placeholder="Search player"
              value={search}
              maxLength={60}
              onChange={(e) => setSearch(e.target.value)}
            />
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
          <Menu
            title="Sportsbooks"
            items={books.map((id): [string, string] => [id, bookName(id)])}
            off={offBooks}
            setOff={setOffBooks}
          />
          {status.manual_fetch_enabled === true && (
            <>
              <h3>Fetch prop odds</h3>
              <label className="field">
                <span>LEAGUE</span>
                <select
                  value={fetchSport}
                  onChange={(e) => {
                    fetchInitialized.current = false;
                    setFetchSport(e.target.value);
                    setFetchMarkets([]);
                  }}
                >
                  {status.sports.map((s) => (
                    <option key={s.key} value={s.key}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </label>
              <details className="arb-menu props-fetch-menu">
                <summary>Markets to fetch ({fetchMarkets.length})</summary>
                <div className="arb-menu-pop">
                  <fieldset className="ev-books">
                    <legend>
                      MARKETS TO FETCH{" "}
                      <button
                        type="button"
                        className="link-button"
                        onClick={() =>
                          setFetchMarkets(
                            catalog.filter((m) => m.default).map((m) => m.key),
                          )
                        }
                      >
                        default
                      </button>{" "}
                      <button
                        type="button"
                        className="link-button"
                        onClick={() => setFetchMarkets([])}
                      >
                        none
                      </button>
                    </legend>
                    {[...groups].map(([group, items]) => (
                      <div key={group} className="props-group">
                        <small>{group}</small>
                        {items.map((m) => (
                          <label key={m.key}>
                            <input
                              type="checkbox"
                              checked={fetchMarkets.includes(m.key)}
                              onChange={() =>
                                setFetchMarkets((prev) =>
                                  prev.includes(m.key)
                                    ? prev.filter((k) => k !== m.key)
                                    : [...prev, m.key],
                                )
                              }
                            />
                            {m.label}
                          </label>
                        ))}
                      </div>
                    ))}
                  </fieldset>
                </div>
              </details>
              <label className="field">
                <span>GAMES (SOONEST FIRST) · {fetchEvents}</span>
                <input
                  type="range"
                  min="1"
                  max={status.max_events}
                  value={fetchEvents}
                  onChange={(e) => setFetchEvents(Number(e.target.value))}
                />
              </label>
              <button
                className="button"
                disabled={busy || !fetchMarkets.length}
                onClick={fetchNow}
              >
                {busy ? "Fetching…" : `Fetch props (≤ ${credits(estimate)})`}
              </button>
              {notice && (
                <small
                  role={notice.ok ? "status" : "alert"}
                  className={notice.ok ? "props-ok" : "mid-loss"}
                >
                  {notice.text}
                </small>
              )}
            </>
          )}
        </FeedFilters>
        <div className="ev-main">
          <div className="ev-count">
            <strong>{visible.length}</strong> of {all.length} bets
            {status.last_success_at && (
              <> · fetched {date(status.last_success_at)}</>
            )}
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
          <div
            role="table"
            aria-label="Player prop bets"
            className="ev-grid props-grid"
          >
            <div role="row" className="ev-head">
              <span role="columnheader">EV</span>
              <span role="columnheader">Event</span>
              <span role="columnheader">Player &amp; bet</span>
              <span role="columnheader">Sportsbook</span>
              <span role="columnheader">Win chance &amp; fair odds</span>
              <span role="columnheader">Scanned</span>
            </div>
            {visible.length === 0 ? (
              <div className="empty-state">
                <h3>
                  {all.length
                    ? "No props match your filters"
                    : "No EV props available yet"}
                </h3>
                <p>
                  {hiddenAsOld
                    ? `Prop odds go stale quickly, so fetches older than ${Math.round(status.max_age_seconds / 60)} minutes are hidden. The last fetch was ${date(status.last_success_at ?? "")}. This feed will use the next scheduled capture.`
                    : "No positive estimated edges meet these filters. Check your maximum odds, EV limit and enabled books. One-sided estimates require two other matching reference books; automatic mode uses paired prices, observed margins, then a labeled 10% assumption with a 20% stress check. Set market width to No limit to allow prices with unavailable width."}
                </p>
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
              <div role="rowgroup">
                {visible.slice(0, shown).map((v) => (
                  <div
                    key={v.id}
                    role="row"
                    tabIndex={0}
                    aria-selected={
                      parlay?.draft.active
                        ? parlay.selected(builderLeg(v, "prop").key)
                        : v.id === selected
                    }
                    className={`props-row ${v.id === selected ? "selected" : ""} ${parlay?.draft.active && parlay.selected(builderLeg(v, "prop").key) ? "parlay-selected" : ""}`}
                    onClick={() => select(v)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        select(v);
                      }
                    }}
                  >
                    <div role="cell" className="ev-cell ev-edge">
                      {parlay?.draft.active &&
                        parlay.selected(builderLeg(v, "prop").key) && (
                          <span
                            className="parlay-check"
                            aria-label="Added to parlay"
                          >
                            ✓
                          </span>
                        )}
                      <span className="ev-badge">{percent(v.ev, true)}</span>
                      <PlacedChip leg={v} />
                    </div>
                    <div role="cell" className="ev-cell ev-event">
                      <Matchup text={v.matchup} sportKey={v.sportKey} />
                      <small>{date(v.startsAt)}</small>
                    </div>
                    <div role="cell" className="ev-cell ev-market">
                      <span className="player-line">
                        <Avatar
                          kind="player"
                          name={v.player}
                          sportKey={v.sportKey}
                          size={36}
                        />
                        <span className="player-text">
                          <small>{v.market}</small>
                          <strong>{v.line}</strong>
                          <Link
                            href={labHref(v.id)}
                            className="button secondary trend-row-button"
                            aria-label={`Open The Lab for ${v.player}: ${v.line}`}
                            onKeyDown={(event) => event.stopPropagation()}
                            onClick={(event) => event.stopPropagation()}
                          >
                            Trends
                          </Link>
                        </span>
                      </span>
                    </div>
                    <div role="cell" className="ev-cell ev-soft">
                      <span className="ev-action">
                        <span>{v.bookLabel}</span>
                        <b>@ {v.odds}</b>
                        <BetLinkButton
                          compact
                          links={v.links}
                          bookLabel={v.bookLabel}
                          startsAt={v.startsAt}
                        />
                      </span>
                    </div>
                    <div role="cell" className="ev-cell ev-sharp">
                      <strong>{percent(v.fair)} estimated chance</strong>
                      <small>Fair {v.fairOdds ?? "—"}</small>
                      <small>{v.sharps}</small>
                      {v.referenceWeights && (
                        <details>
                          <summary>Reference weights</summary>
                          <small>{v.referenceWeights}</small>
                        </details>
                      )}
                      {v.allocationSensitivity && (
                        <details>
                          <summary>One-sided sensitivity</summary>
                          <small>
                            EV range {percent(v.allocationSensitivity.ev_min)}{" "}
                            to {percent(v.allocationSensitivity.ev_max)} under
                            the stated margin ceilings and nonnegative vig
                            assumptions. This is not a confidence interval. The
                            headline estimate assumes proportional margin
                            allocation.
                          </small>
                        </details>
                      )}
                      {v.inferredMargin && (
                        <small>Modeled: observed-margin estimate</small>
                      )}
                      {v.assumedMargin != null && (
                        <small>
                          Modeled: {percent(v.assumedMargin)} assumed margin
                          {v.stressMargin &&
                            ` · EV uses ${percent(v.stressMargin)} stress`}
                        </small>
                      )}
                    </div>
                    <div role="cell" className="ev-cell ev-time">
                      <Age value={v.observedAt} />
                    </div>
                  </div>
                ))}
                {shown < visible.length && (
                  <button
                    className="button secondary"
                    onClick={() => setShown((n) => n + PAGE)}
                  >
                    Show more ({visible.length - shown} left)
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
        {openBet && (
          <div className="kelly-backdrop" onClick={() => setSelected(null)} />
        )}
        <KellyWidget
          vm={openBet}
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

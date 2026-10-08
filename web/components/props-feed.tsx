"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  american,
  ageLabel,
  compareDecimal,
  date,
  divDecimal,
  percent,
  shiftDecimal,
  usd,
} from "../../frontend/format.mjs";
import {
  loadProps,
  refreshProps,
  type PropBet,
  type PropsStatus,
} from "../lib/refresh-api";
import {
  BANKROLL_KEY,
  KellyWidget,
  MULTIPLIER_KEY,
  SLIP_KEY,
  type KellyVm,
  type SlipBet,
} from "./ev-feed";
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
const bookName = (id: string) => BOOK_NAMES[id] ?? id;
const SETTINGS_KEY = "corner.props-settings";
const PAGE = 100;

interface Vm extends KellyVm {
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
  sharps: string;
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
  const side = b.point == null ? b.side : `${b.side} ${shiftDecimal(b.point, 0)}`;
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
    decimalOdds: b.price,
    odds: american(b.price),
    fairOdds,
    prob: Number(b.fair_probability),
    fair: b.fair_probability,
    sharps: b.sharps.map(bookName).join(" + "),
    observedAt: b.observed_at,
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
  const [, tick] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(timer);
  }, []);
  return <span className="ev-age">{value ? ageLabel(value) : "—"}</span>;
}

export default function PropsFeed({ reload }: { reload: number }) {
  const [status, setStatus] = useState<PropsStatus | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [sportKey, setSportKey] = useState("");
  const [marketKey, setMarketKey] = useState("");
  const [search, setSearch] = useState("");
  const [eventId, setEventId] = useState("");
  const [minEv, setMinEv] = useState("0");
  const [minOdds, setMinOdds] = useState("");
  const [maxOdds, setMaxOdds] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("ev");
  const [offBooks, setOffBooks] = useState<Set<string>>(new Set());
  const [shown, setShown] = useState(PAGE);
  const [selected, setSelected] = useState<string | null>(null);
  const [bankroll, setBankroll] = useState("1000");
  const [multiplier, setMultiplier] = useState("0.25");
  const [slip, setSlip] = useState<SlipBet[]>([]);
  const [slipOpen, setSlipOpen] = useState(false);
  const [slipVersion, setSlipVersion] = useState(0);
  const [fetchSport, setFetchSport] = useState("");
  const [fetchMarkets, setFetchMarkets] = useState<string[]>([]);
  const [fetchEvents, setFetchEvents] = useState(8);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");

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
    try {
      setSlip(JSON.parse(localStorage.getItem(SLIP_KEY) ?? "[]"));
    } catch {
      setSlip([]);
    }
  }, [slipVersion]);

  useEffect(() => {
    const controller = new AbortController();
    setError("");
    loadProps(controller.signal)
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
  }, [retry, reload]);

  const catalog = status?.markets[fetchSport] ?? [];
  useEffect(() => {
    setFetchMarkets(catalog.filter((m) => m.default).map((m) => m.key));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchSport, status?.markets]);

  const all = useMemo(
    () =>
      (status?.bets ?? [])
        .filter((b) => BETTING_BOOKS.includes(b.book))
        .map(toVm)
        .sort(SORTS.ev),
    [status],
  );
  const sports = useMemo(
    () =>
      status
        ? status.sports.filter((s) => all.some((v) => v.sportKey === s.key))
        : [],
    [status, all],
  );
  const inSport = useMemo(
    () => all.filter((v) => !sportKey || v.sportKey === sportKey),
    [all, sportKey],
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
  const books = useMemo(
    () =>
      [...BETTING_BOOKS].sort((a, b) => bookName(a).localeCompare(bookName(b))),
    [],
  );

  const minRatio = shiftDecimal(minEv, -2);
  const lo = oddsToDecimal(minOdds);
  const hi = oddsToDecimal(maxOdds);
  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return inSport
      .filter(
        (v) =>
          !offBooks.has(v.bookId) &&
          (!marketKey || v.marketKey === marketKey) &&
          (!eventId || v.gameId === eventId) &&
          (!needle || v.player.toLowerCase().includes(needle)) &&
          compareDecimal(v.ev, minRatio) >= 0 &&
          (lo === null || Number(v.decimalOdds) >= lo) &&
          (hi === null || Number(v.decimalOdds) <= hi),
      )
      .sort(SORTS[sortKey]);
  }, [inSport, offBooks, marketKey, eventId, search, minRatio, lo, hi, sortKey]);
  useEffect(
    () => setShown(PAGE),
    [sportKey, marketKey, eventId, search, minEv, minOdds, maxOdds, sortKey, offBooks],
  );
  const active = visible.find((v) => v.id === selected) ?? null;

  const estimate = fetchEvents * fetchMarkets.length;
  const wait = status?.retry_after_seconds ?? 0;
  const fetchNow = useCallback(async () => {
    if (!fetchSport || !fetchMarkets.length) return;
    if (
      !window.confirm(
        `Fetch ${fetchMarkets.length} prop market(s) for up to ${fetchEvents} games? This uses up to ${estimate} API credits.`,
      )
    )
      return;
    setBusy(true);
    setNotice("");
    try {
      await refreshProps(fetchSport, fetchMarkets, fetchEvents);
      setRetry((n) => n + 1);
      setSportKey(fetchSport);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Refresh failed.");
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
    <section className="ev-layout props-layout" aria-label="Player props">
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
            value={marketKey}
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
          <select value={eventId} onChange={(e) => setEventId(e.target.value)}>
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
              onClick={() => setOffBooks(new Set(books))}
            >
              none
            </button>
          </legend>
          {books.map((id) => (
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
              {bookName(id)}
            </label>
          ))}
        </fieldset>
        <h3>Fetch prop odds</h3>
        <label className="field">
          <span>LEAGUE</span>
          <select
            value={fetchSport}
            onChange={(e) => setFetchSport(e.target.value)}
          >
            {status.sports.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
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
          disabled={busy || !fetchMarkets.length || wait > 0}
          onClick={fetchNow}
        >
          {busy
            ? "Fetching…"
            : wait > 0
              ? `Wait ${wait}s`
              : `Fetch props (≤ ${estimate} credits)`}
        </button>
        <small>
          Used today: {status.credits_today} / {status.daily_credits} credits
          {status.quota?.["x-requests-remaining"]
            ? ` · ${status.quota["x-requests-remaining"]} left on the key`
            : ""}
          {status.last_result ? ` · Last: ${status.last_result}` : ""}
        </small>
        {notice && (
          <small role="alert" className="mid-loss">
            {notice}
          </small>
        )}
      </aside>
      <div className="ev-main">
        <div className="ev-count">
          <button
            className="button secondary ev-slip-toggle"
            onClick={() => setSlipOpen((o) => !o)}
          >
            My bets ({slip.length})
          </button>
          <strong>{visible.length}</strong> of {all.length} bets
          {status.last_success_at && (
            <> · fetched {date(status.last_success_at)}</>
          )}
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
        {slipOpen && (
          <div className="ev-slip">
            {slip.length === 0 ? (
              <p>No bets logged yet. Select a row and use One-click bet.</p>
            ) : (
              <>
                <table>
                  <tbody>
                    {[...slip].reverse().map((b) => (
                      <tr key={b.at}>
                        <td>{date(b.at)}</td>
                        <td>
                          {b.matchup} · {b.line}
                        </td>
                        <td>
                          {b.book} @ {b.odds}
                        </td>
                        <td>{usd(b.stake)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <button
                  className="button secondary"
                  onClick={() => {
                    localStorage.removeItem(SLIP_KEY);
                    setSlipVersion((n) => n + 1);
                  }}
                >
                  Clear log
                </button>
              </>
            )}
          </div>
        )}
        <div
          role="table"
          aria-label="Player prop bets"
          className="ev-grid props-grid"
        >
          <div role="row" className="ev-head">
            <span role="columnheader">EV</span>
            <span role="columnheader">Event</span>
            <span role="columnheader">Player &amp; bet</span>
            <span role="columnheader">Soft book</span>
            <span role="columnheader">Win chance &amp; fair odds</span>
            <span role="columnheader">Scanned</span>
          </div>
          {visible.length === 0 ? (
            <div className="empty-state">
              <h3>No +EV prop bets right now</h3>
              <p>
                Fetch prop odds, lower the minimum EV, or re-enable books. Bets
                need at least two sharp books pricing both sides of the same line.
              </p>
            </div>
          ) : (
            <div role="rowgroup">
              {visible.slice(0, shown).map((v) => (
                <div
                  key={v.id}
                  role="row"
                  tabIndex={0}
                  aria-selected={v.id === selected}
                  className={`props-row ${v.id === selected ? "selected" : ""}`}
                  onClick={() => setSelected(v.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      setSelected(v.id);
                    }
                  }}
                >
                  <div role="cell" className="ev-cell ev-edge">
                    <span className="ev-badge">{percent(v.ev, true)}</span>
                  </div>
                  <div role="cell" className="ev-cell ev-event">
                    <strong>{v.matchup}</strong>
                    <small>{date(v.startsAt)}</small>
                  </div>
                  <div role="cell" className="ev-cell ev-market">
                    <small>{v.market}</small>
                    <strong>{v.line}</strong>
                  </div>
                  <div role="cell" className="ev-cell ev-soft">
                    <span className="ev-action">
                      <span>{v.bookLabel}</span>
                      <b>@ {v.odds}</b>
                    </span>
                  </div>
                  <div role="cell" className="ev-cell ev-sharp">
                    <strong>{percent(v.fair)} chance</strong>
                    <small>
                      Fair {v.fairOdds ?? "—"} · {v.sharps}
                    </small>
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
        onLogged={() => setSlipVersion((n) => n + 1)}
      />
    </section>
  );
}

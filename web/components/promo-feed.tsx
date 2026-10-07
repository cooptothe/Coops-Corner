"use client";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  MARKETS,
  american,
  date,
  selection,
  sport,
  usd,
} from "../../frontend/format.mjs";
import type { Capabilities, Game, Meta, Quote } from "../lib/contracts";
import {
  convert,
  parseAmerican,
  toDecimal,
  type PromoType,
} from "../lib/promo-math";
import { Age, CopyButton, Menu, shortBook } from "./arb-feed";

type Data = { caps: Capabilities; games: Game[]; quotes: Quote[]; meta: Meta };
interface Leg {
  quoteId: string;
  bookId: string;
  bookLabel: string;
  label: string;
  odds: string;
  decimal: number;
}
interface Vm {
  id: string;
  matchup: string;
  league: string;
  startsAt: string;
  sportKey: string;
  marketKey: string;
  market: string;
  promo: Leg;
  hedge: Leg;
  rate: number;
  observedAt: string;
  sig: string;
}

type SortKey = "rate" | "time" | "promo_odds" | "scanned";
const SORT_LABELS: [SortKey, string][] = [
  ["rate", "Conversion % (highest)"],
  ["time", "Event time (soonest)"],
  ["promo_odds", "Promo odds (highest)"],
  ["scanned", "Newest scan"],
];
const startMs = (v: Vm) =>
  v.startsAt ? new Date(v.startsAt).getTime() : Infinity;
const ROW_HEIGHT = { wide: 96, compact: 200 };
const OVERSCAN = 6;
const VIEW_HEIGHT = 680;
const SETTINGS_KEY = "corner.promo-settings";
const AMOUNT = /^\d{1,7}(\.\d{1,2})?$/;
const PCT = /^\d{1,3}$/;
const OPPOSITE: Record<string, string> = {
  home: "away",
  away: "home",
  over: "under",
  under: "over",
};
const MARKET_NAMES = MARKETS as Record<string, string>;
const TYPES: { id: PromoType; name: string; help: string }[] = [
  {
    id: "bonus",
    name: "Bonus bet",
    help: "Stake is not returned. Best on +200 to +500 underdogs.",
  },
  {
    id: "credit",
    name: "Site credit",
    help: "Stake is returned, so tight even-money lines work best.",
  },
  {
    id: "nosweat",
    name: "No-sweat bet",
    help: "Cash bet; a loss refunds a bonus bet worth the rate below.",
  },
];
const DEFAULT_ODDS: Record<PromoType, [string, string]> = {
  bonus: ["+200", "+500"],
  credit: ["", ""],
  nosweat: ["+150", "+400"],
};

const money = (n: number) => usd(n.toFixed(2));
const pct = (n: number) => `${(n * 100).toFixed(1)}%`;

function leg(q: Quote, books: Map<string, string>): Leg {
  return {
    quoteId: q.id,
    bookId: q.sportsbook_id,
    bookLabel: shortBook(books.get(q.sportsbook_id) ?? q.sportsbook_id),
    label: selection(q),
    odds: american(q.decimal_odds),
    decimal: Number(q.decimal_odds),
  };
}

const Row = memo(
  function Row({
    vm,
    face,
    type,
    refund,
    top,
    selected,
    onSelect,
  }: {
    vm: Vm;
    face: number;
    type: PromoType;
    refund: number;
    top: number;
    selected: boolean;
    onSelect: (vm: Vm) => void;
  }) {
    const c = convert(type, face, vm.promo.decimal, vm.hedge.decimal, refund);
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
          <span className="ev-badge arb-badge">{pct(vm.rate)}</span>
        </div>
        <div role="cell" className="ev-cell ev-event">
          <span className="ev-league">
            {vm.league} · {vm.market}
          </span>
          <strong>{vm.matchup}</strong>
          <small>
            {vm.startsAt ? date(vm.startsAt) : ""}
            {c ? ` · hedge ${money(c.hedge)} → ${money(c.profit)}` : ""}
          </small>
        </div>
        <div role="cell" className="ev-cell arb-legs">
          {[
            ["Promo", vm.promo],
            ["Hedge", vm.hedge],
          ].map(([tag, l]) => {
            const g = l as Leg;
            return (
              <div className="arb-leg" key={g.quoteId}>
                <span className="arb-book">
                  {tag as string} · {g.bookLabel}
                </span>
                <span className="arb-side">{g.label}</span>
                <b>{g.odds}</b>
              </div>
            );
          })}
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
    a.vm.rate === b.vm.rate &&
    a.vm.observedAt === b.vm.observedAt &&
    a.face === b.face &&
    a.type === b.type &&
    a.refund === b.refund &&
    a.top === b.top &&
    a.selected === b.selected,
);

function Calculator({
  vm,
  shift,
  onAccept,
  type,
  face,
  setFace,
  refund,
  onClose,
}: {
  vm: Vm | null;
  shift: "ok" | "moved" | "dropped";
  onAccept: () => void;
  type: PromoType;
  face: string;
  setFace: (v: string) => void;
  refund: number;
  onClose: () => void;
}) {
  const valid = AMOUNT.test(face) && Number(face) > 0;
  const sig = vm?.sig ?? "";
  const c = useMemo(
    () =>
      vm && valid
        ? convert(
            type,
            Number(face),
            vm.promo.decimal,
            vm.hedge.decimal,
            refund,
          )
        : null,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [sig, type, face, valid, refund],
  );
  const noun = type === "nosweat" ? "CASH BET ($)" : "PROMO VALUE ($)";
  return (
    <aside
      className={`kelly-panel arb-calc ${vm ? "open" : ""}`}
      aria-label="Promo calculator"
    >
      <button className="kelly-close" onClick={onClose} aria-label="Close">
        ✕
      </button>
      <h3>Promo calculator</h3>
      {!vm ? (
        <p className="kelly-empty">Select a conversion to size the hedge.</p>
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
            <span>
              {vm.league} · {vm.market}
            </span>
            <span className="ev-badge arb-badge">{pct(vm.rate)}</span>
          </div>
          <label className="field">
            <span>{noun}</span>
            <input
              inputMode="decimal"
              value={face}
              maxLength={10}
              aria-invalid={!valid}
              onChange={(e) => setFace(e.target.value.trim())}
            />
          </label>
          <div className="arb-stake">
            <span>
              1 · Place the promo on {vm.promo.bookLabel} · {vm.promo.label} @{" "}
              {vm.promo.odds}
            </span>
            <output>{valid ? money(Number(face)) : "—"}</output>
            <span />
          </div>
          {!valid || !c ? (
            <p className="kelly-empty">Enter an amount greater than zero.</p>
          ) : (
            <>
              <div className="arb-stake">
                <span>
                  2 · Cash hedge on {vm.hedge.bookLabel} · {vm.hedge.label} @{" "}
                  {vm.hedge.odds}
                </span>
                <output>{money(c.hedge)}</output>
                <CopyButton value={c.hedge.toFixed(2)} label="hedge" />
              </div>
              <div className="arb-summary">
                <span>If {vm.promo.label} wins</span>
                <b>{money(c.ifPromoWins)}</b>
                <span>If {vm.hedge.label} wins</span>
                <b>{money(c.ifHedgeWins)}</b>
                <span>Guaranteed cash profit</span>
                <b className="arb-net">{money(c.profit)}</b>
                <span>Conversion</span>
                <b className="arb-net">{pct(c.rate)}</b>
              </div>
              {type === "nosweat" && (
                <small className="kelly-note">
                  The loss case counts the refund voucher at{" "}
                  {Math.round(refund * 100)}% of its face value; that cash only
                  arrives after you convert the voucher.
                </small>
              )}
              {type === "bonus" && (
                <small className="kelly-note">
                  The bonus stake is not returned, so a win pays only the
                  profit.
                </small>
              )}
            </>
          )}
        </>
      )}
    </aside>
  );
}

export default function PromoFeed({ data }: { data: Data }) {
  const [type, setType] = useState<PromoType>("bonus");
  const [face, setFace] = useState("100");
  const [refund, setRefund] = useState("75");
  const [promoBook, setPromoBook] = useState("");
  const [minOdds, setMinOdds] = useState(DEFAULT_ODDS.bonus[0]);
  const [maxOdds, setMaxOdds] = useState(DEFAULT_ODDS.bonus[1]);
  const [minRate, setMinRate] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("rate");
  const [offBooks, setOffBooks] = useState<Set<string>>(new Set());
  const [offSports, setOffSports] = useState<Set<string>>(new Set());
  const [offMarkets, setOffMarkets] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<Vm | null>(null);
  const loaded = useRef(false);

  useEffect(() => {
    try {
      const s = JSON.parse(localStorage.getItem(SETTINGS_KEY) ?? "{}");
      if (TYPES.some((t) => t.id === s.type)) setType(s.type);
      if (typeof s.face === "string" && AMOUNT.test(s.face)) setFace(s.face);
      if (typeof s.refund === "string" && PCT.test(s.refund))
        setRefund(s.refund);
      if (typeof s.promoBook === "string") setPromoBook(s.promoBook);
      if (SORT_LABELS.some(([k]) => k === s.sortKey)) setSortKey(s.sortKey);
      if (typeof s.minOdds === "string") setMinOdds(s.minOdds);
      if (typeof s.maxOdds === "string") setMaxOdds(s.maxOdds);
      if (
        typeof s.minRate === "string" &&
        (s.minRate === "" || PCT.test(s.minRate))
      )
        setMinRate(s.minRate);
      if (Array.isArray(s.offBooks))
        setOffBooks(new Set(s.offBooks.map(String)));
      if (Array.isArray(s.offSports))
        setOffSports(new Set(s.offSports.map(String)));
      if (Array.isArray(s.offMarkets))
        setOffMarkets(new Set(s.offMarkets.map(String)));
    } catch {}
    loaded.current = true;
  }, []);
  useEffect(() => {
    if (!loaded.current) return;
    localStorage.setItem(
      SETTINGS_KEY,
      JSON.stringify({
        type,
        face,
        refund,
        promoBook,
        minOdds,
        maxOdds,
        minRate,
        sortKey,
        offBooks: [...offBooks],
        offSports: [...offSports],
        offMarkets: [...offMarkets],
      }),
    );
  }, [
    type,
    face,
    refund,
    promoBook,
    minOdds,
    maxOdds,
    minRate,
    offBooks,
    offSports,
    offMarkets,
  ]);

  const books = useMemo(
    () => new Map(data.caps.books.map((b) => [b.id, b.name])),
    [data],
  );
  const games = useMemo(
    () => new Map(data.games.map((g) => [g.id, g])),
    [data],
  );
  // Two-way contracts only: a draw outcome means a hedge could not cover every result.
  const contracts = useMemo(() => {
    const groups = new Map<string, Quote[]>();
    for (const q of data.quotes) {
      if (
        q.market_key.endsWith("_lay") ||
        !/^0(?:\.0*)?$/.test(q.commission_rate)
      )
        continue;
      const list = groups.get(q.contract_id);
      if (list) list.push(q);
      else groups.set(q.contract_id, [q]);
    }
    for (const [id, list] of groups)
      if (list.some((q) => !(q.side in OPPOSITE))) groups.delete(id);
    return groups;
  }, [data]);

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
    return [...m].sort((a, b) => a[1].localeCompare(b[1]));
  }, [data]);
  const marketItems = useMemo((): [string, string][] => {
    const m = new Map<string, string>();
    for (const q of data.quotes)
      if (!q.market_key.endsWith("_lay"))
        m.set(q.market_key, MARKET_NAMES[q.market_key] ?? q.market_key);
    return [...m].sort((a, b) => a[1].localeCompare(b[1]));
  }, [data]);

  const faceValue = AMOUNT.test(face) && Number(face) > 0 ? Number(face) : 100;
  const refundRate = PCT.test(refund)
    ? Math.min(Number(refund), 100) / 100
    : 0.75;
  const lowOdds = minOdds ? parseAmerican(minOdds) : null;
  const highOdds = maxOdds ? parseAmerican(maxOdds) : null;
  const rateLimit = PCT.test(minRate) ? Number(minRate) / 100 : null;
  const oddsBad =
    (minOdds !== "" && lowOdds === null) ||
    (maxOdds !== "" && highOdds === null);

  const all = useMemo(() => {
    if (!promoBook) return [];
    const out: Vm[] = [];
    for (const list of contracts.values()) {
      for (const p of list) {
        if (p.sportsbook_id !== promoBook) continue;
        const g = games.get(p.game_id);
        if (
          !g ||
          (g.starts_at && new Date(g.starts_at).getTime() <= Date.now())
        )
          continue;
        if (offSports.has(g.sport_key) || offMarkets.has(p.market_key))
          continue;
        const d1 = Number(p.decimal_odds);
        if (lowOdds !== null && d1 < toDecimal(lowOdds) - 1e-9) continue;
        if (highOdds !== null && d1 > toDecimal(highOdds) + 1e-9) continue;
        let best: Quote | null = null;
        for (const h of list) {
          if (
            h.sportsbook_id === promoBook ||
            offBooks.has(h.sportsbook_id) ||
            h.side !== OPPOSITE[p.side]
          )
            continue;
          if (!best || Number(h.decimal_odds) > Number(best.decimal_odds))
            best = h;
        }
        if (!best) continue;
        const c = convert(
          type,
          faceValue,
          d1,
          Number(best.decimal_odds),
          refundRate,
        );
        if (!c) continue;
        const pl = leg(p, books);
        const hl = leg(best, books);
        out.push({
          id: `${p.id}:${best.id}`,
          matchup: g.name,
          league: g.competition ?? sport(g.sport_key),
          startsAt: g.starts_at ?? "",
          sportKey: g.sport_key,
          marketKey: p.market_key,
          market: MARKET_NAMES[p.market_key] ?? p.market_key,
          promo: pl,
          hedge: hl,
          rate: c.rate,
          observedAt:
            p.observed_at > best.observed_at ? p.observed_at : best.observed_at,
          sig: `${pl.odds}|${hl.odds}`,
        });
      }
    }
    return out;
  }, [
    contracts,
    games,
    books,
    promoBook,
    type,
    faceValue,
    refundRate,
    lowOdds,
    highOdds,
    offBooks,
    offSports,
    offMarkets,
  ]);

  const visible = useMemo(
    () =>
      all
        .filter((v) => rateLimit === null || v.rate >= rateLimit)
        .sort((a, b) => {
          switch (sortKey) {
            case "time":
              return startMs(a) - startMs(b);
            case "promo_odds":
              return b.promo.decimal - a.promo.decimal;
            case "scanned":
              return b.observedAt.localeCompare(a.observedAt);
            default:
              return b.rate - a.rate;
          }
        })
        .slice(0, 500),
    [all, rateLimit, sortKey],
  );
  const byId = useMemo(() => new Map(all.map((v) => [v.id, v])), [all]);
  const avg = visible.length
    ? visible.reduce((s, v) => s + v.rate, 0) / visible.length
    : null;

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
  const first = Math.max(0, Math.floor(scroll / height) - OVERSCAN);
  const last = Math.min(
    visible.length,
    Math.ceil((scroll + VIEW_HEIGHT) / height) + OVERSCAN,
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

  const changeType = (t: PromoType) => {
    setType(t);
    setMinOdds(DEFAULT_ODDS[t][0]);
    setMaxOdds(DEFAULT_ODDS[t][1]);
    setSelected(null);
  };
  const help = TYPES.find((t) => t.id === type)?.help;

  return (
    <section className="arb-layout" aria-label="Promo converter">
      <div className="arb-bar">
        <div
          className="arb-modes pr-types"
          role="group"
          aria-label="Promo type"
        >
          {TYPES.map((t) => (
            <button
              key={t.id}
              type="button"
              className={type === t.id ? "active" : ""}
              aria-pressed={type === t.id}
              onClick={() => changeType(t.id)}
            >
              {t.name}
            </button>
          ))}
        </div>
        <label className="field mid-small">
          <span>PROMO SPORTSBOOK</span>
          <select
            value={promoBook}
            onChange={(e) => setPromoBook(e.target.value)}
          >
            <option value="">Choose a book…</option>
            {bookItems.map(([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <label className="field mid-small">
          <span>{type === "nosweat" ? "CASH BET ($)" : "PROMO VALUE ($)"}</span>
          <input
            inputMode="decimal"
            value={face}
            maxLength={10}
            aria-invalid={!AMOUNT.test(face)}
            onChange={(e) => setFace(e.target.value.trim())}
          />
        </label>
        <label className="field mid-small">
          <span>MIN PROMO ODDS</span>
          <input
            inputMode="numeric"
            placeholder="any"
            value={minOdds}
            maxLength={6}
            aria-invalid={minOdds !== "" && lowOdds === null}
            onChange={(e) => setMinOdds(e.target.value.trim())}
          />
        </label>
        <label className="field mid-small">
          <span>MAX PROMO ODDS</span>
          <input
            inputMode="numeric"
            placeholder="any"
            value={maxOdds}
            maxLength={6}
            aria-invalid={maxOdds !== "" && highOdds === null}
            onChange={(e) => setMaxOdds(e.target.value.trim())}
          />
        </label>
        {type === "nosweat" && (
          <label className="field mid-small">
            <span>VOUCHER VALUE %</span>
            <input
              inputMode="numeric"
              value={refund}
              maxLength={3}
              aria-invalid={!PCT.test(refund)}
              onChange={(e) => setRefund(e.target.value.trim())}
            />
          </label>
        )}
        <label className="field mid-small">
          <span>MIN CONVERSION %</span>
          <input
            inputMode="numeric"
            placeholder="any"
            value={minRate}
            maxLength={3}
            aria-invalid={minRate !== "" && rateLimit === null}
            onChange={(e) => setMinRate(e.target.value.trim())}
          />
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
        <Menu
          title="Hedge books"
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
        <span className="arb-status" role="status">
          <i className="arb-pulse" aria-hidden="true" />
          Prices as of {date(data.meta.captured_at)}
        </span>
      </div>
      <div className="mid-metrics" aria-label="Promo summary">
        <div>
          <span>CONVERSIONS FOUND</span>
          <b>{visible.length}</b>
        </div>
        <div>
          <span>AVG. CONVERSION</span>
          <b>{avg === null ? "—" : pct(avg)}</b>
        </div>
        <div>
          <span>BEST CONVERSION</span>
          <b className="arb-net">
            {visible.length
              ? pct(Math.max(...visible.map((v) => v.rate)))
              : "—"}
          </b>
        </div>
      </div>
      <div className="arb-body">
        <div className="ev-main">
          <div className="ev-count">
            <strong>{visible.length}</strong> conversions · {help} Hedges are
            two-way markets only.
          </div>
          <div
            role="table"
            aria-label="Promo conversions"
            className="ev-grid arb-grid"
          >
            <div role="row" className="ev-head">
              <span role="columnheader">Conversion</span>
              <span role="columnheader">Event</span>
              <span role="columnheader">Promo &amp; hedge</span>
              <span role="columnheader">Scanned</span>
            </div>
            {!promoBook ? (
              <div className="empty-state">
                <h3>Pick your promo sportsbook</h3>
                <p>
                  Choose the book that holds your bonus, then every game is
                  scanned for the best cash hedge at the other books.
                </p>
              </div>
            ) : oddsBad ? (
              <div className="empty-state">
                <h3>Check the odds range</h3>
                <p>
                  Use American odds such as +200 or -110, or leave a box empty.
                </p>
              </div>
            ) : visible.length === 0 ? (
              <div className="empty-state">
                <h3>No conversions match</h3>
                <p>
                  Widen the promo odds range, lower the minimum conversion,
                  re-enable hedge books, leagues or markets, or press Refresh
                  odds.
                </p>
              </div>
            ) : (
              <div
                ref={viewport}
                className="ev-viewport"
                style={{
                  height: Math.min(VIEW_HEIGHT, visible.length * height),
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
                      face={faceValue}
                      type={type}
                      refund={refundRate}
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
          type={type}
          face={face}
          setFace={setFace}
          refund={refundRate}
          onClose={() => setSelected(null)}
        />
      </div>
    </section>
  );
}

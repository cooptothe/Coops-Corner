"use client";
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
import { choice, list as asList, sorted, text } from "../lib/settings-fields";
import { userStorage } from "../lib/user-storage";
import type { Capabilities, Game, Meta, Quote } from "../lib/contracts";
import {
  WIDE_MARKET_CENTS,
  convert,
  type Boost,
  type Conversion,
  efficiencyTier,
  marketWidthCents,
  parseAmerican,
  toDecimal,
  type PromoType,
} from "../lib/promo-math";
import { quoteRef, type NewBet } from "../lib/slip";
import type { RefValue } from "../lib/tracker-api";
import { Age, Menu, shortBook } from "./arb-feed";
import { LogBetButton, SlipLog, SlipToggle, useSlip } from "./bet-slip";
import { FeedChangeNote, useFeedChanges } from "./feed-updates";
import { LegLinks } from "./bet-link";
import type { QuoteLinks } from "../lib/bet-links";
import { SettingsBar, useToolSettings } from "./tool-settings";
import { Matchup } from "./media";

type Data = { caps: Capabilities; games: Game[]; quotes: Quote[]; meta: Meta };
interface Leg {
  quoteId: string;
  bookId: string;
  bookLabel: string;
  label: string;
  odds: string;
  decimal: number;
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
  promo: Leg;
  hedge: Leg;
  rate: number;
  widthCents: number;
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
const ROW_HEIGHT = { wide: 132, compact: 290 };
const OVERSCAN = 6;
const VIEW_HEIGHT = 680;
const SETTINGS_KEY = "corner.promo-settings";
const AMOUNT = /^\d{1,7}(\.\d{1,2})?$/;
const PCT = /^\d{1,3}$/;
const DEFAULT_HEDGE_LIMIT = "1000";
const OPPOSITE: Record<string, string> = {
  home: "away",
  away: "home",
  over: "under",
  under: "over",
};
const MARKET_NAMES = MARKETS as Record<string, string>;
const TYPES: {
  id: PromoType;
  name: string;
  full: string;
  help: string;
}[] = [
  {
    id: "bonus",
    name: "Bonus bet",
    full: "Bonus Bet (Stake Not Returned)",
    help: "Stake is not returned. Best on +200 to +500 underdogs.",
  },
  {
    id: "credit",
    name: "Site credit",
    full: "Site Credit (Stake Returned)",
    help: "Stake is returned, so tight even-money lines work best.",
  },
  {
    id: "nosweat",
    name: "Risk-free bet",
    full: "Risk-Free Bet (Contingent Refund)",
    help: "Cash bet; a loss refunds a bonus bet worth the voucher value below.",
  },
  {
    id: "boost",
    name: "Profit boost",
    full: "Profit Boost (Cash Stake, Boosted Winnings)",
    help: "Cash bet whose winnings are boosted. Best on underdogs against a tight hedge.",
  },
];
const TYPE_NAME = Object.fromEntries(
  TYPES.map((t) => [t.id, t.name]),
) as Record<PromoType, string>;
const sizeLabel = (type: PromoType) =>
  type === "nosweat"
    ? "RISK-FREE STAKE ($)"
    : type === "boost"
      ? "CASH STAKE ($)"
      : "PROMO INPUT SIZE ($)";
const DEFAULT_ODDS: Record<PromoType, [string, string]> = {
  bonus: ["+200", "+500"],
  credit: ["", ""],
  nosweat: ["+150", "+400"],
  boost: ["", ""],
};

// Profit boost terms as typed. Empty limits mean the sportsbook sets none.
interface BoostFields {
  percent: string;
  maxStake: string;
  maxExtra: string;
}
const DEFAULT_BOOST: BoostFields = {
  percent: "50",
  maxStake: "100",
  maxExtra: "",
};
const BOOST_PCT = /^\d{1,4}(\.\d{1,2})?$/;
const limitOk = (v: string) => v === "" || (AMOUNT.test(v) && Number(v) > 0);
const boostValid = (b: BoostFields) =>
  BOOST_PCT.test(b.percent) && limitOk(b.maxStake) && limitOk(b.maxExtra);
const toBoost = (b: BoostFields): Boost => ({
  percent: BOOST_PCT.test(b.percent) ? Number(b.percent) / 100 : 0,
  maxStake:
    b.maxStake !== "" && limitOk(b.maxStake) ? Number(b.maxStake) : undefined,
  maxExtra:
    b.maxExtra !== "" && limitOk(b.maxExtra) ? Number(b.maxExtra) : undefined,
});

const money = (n: number) => usd(n.toFixed(2));
const pct = (n: number) => `${(n * 100).toFixed(1)}%`;
const hedgeLimit = (text: string) =>
  AMOUNT.test(text) && Number(text) > 0 ? Number(text) : Infinity;

function CopyIconButton({ value, label }: { value: string; label: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      className={`promo-copy ${done ? "done" : ""}`}
      aria-label={done ? `Copied ${label}` : `Copy ${label}`}
      title={done ? "Copied" : `Copy ${label}`}
      onClick={async (e) => {
        e.stopPropagation();
        try {
          await navigator.clipboard.writeText(value);
          setDone(true);
          setTimeout(() => setDone(false), 1200);
        } catch {}
      }}
    >
      <svg
        viewBox="0 0 24 24"
        width="15"
        height="15"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        {done ? (
          <path d="M5 13l4 4L19 7" />
        ) : (
          <>
            <rect x="9" y="9" width="11" height="11" rx="2" />
            <path d="M5 15V6a2 2 0 0 1 2-2h9" />
          </>
        )}
      </svg>
    </button>
  );
}

function Efficiency({ rate, type }: { rate: number; type: PromoType }) {
  const tier = efficiencyTier(rate, type);
  return (
    <span
      className={`promo-eff eff-${tier}`}
      title={`${tier} ${type === "boost" ? "return on capital" : "conversion"}`}
    >
      {pct(rate)}
    </span>
  );
}

function Warnings({
  hedge,
  limit,
  widthCents,
  boostCapped = false,
}: {
  hedge: number | null;
  limit: number;
  widthCents: number;
  boostCapped?: boolean;
}) {
  const over = hedge !== null && hedge > limit;
  const wide = widthCents > WIDE_MARKET_CENTS;
  if (!over && !wide && !boostCapped) return null;
  return (
    <span className="promo-warns">
      {boostCapped && (
        <span
          className="promo-warn"
          title="Part of the stake or the winnings is past the boost limits, so the boost is smaller than its percentage."
        >
          ⚠ Boost limit reached
        </span>
      )}
      {over && (
        <span
          className="promo-warn"
          title={`The ${money(hedge)} hedge is above your ${money(limit)} limit; books may not accept it.`}
        >
          ⚠ Over hedge limit
        </span>
      )}
      {wide && (
        <span
          className="promo-warn"
          title="The two sides are priced far apart, so the hedge is expensive."
        >
          ⚠ Wide market · {widthCents}¢
        </span>
      )}
    </span>
  );
}

function leg(q: Quote, books: Map<string, string>): Leg {
  return {
    quoteId: q.id,
    bookId: q.sportsbook_id,
    bookLabel: shortBook(books.get(q.sportsbook_id) ?? q.sportsbook_id),
    label: selection(q),
    odds: american(q.decimal_odds),
    decimal: Number(q.decimal_odds),
    ref: quoteRef(q),
    links: q.links ?? null,
  };
}

const Row = memo(
  function Row({
    vm,
    face,
    type,
    refund,
    boost,
    limit,
    top,
    selected,
    onSelect,
  }: {
    vm: Vm;
    face: number;
    type: PromoType;
    refund: number;
    boost: Boost;
    limit: number;
    top: number;
    selected: boolean;
    onSelect: (vm: Vm) => void;
  }) {
    const c = convert(
      type,
      face,
      vm.promo.decimal,
      vm.hedge.decimal,
      refund,
      boost,
    );
    return (
      <div
        role="row"
        tabIndex={0}
        aria-selected={selected}
        className={`ev-row promo-row ${selected ? "selected" : ""}`}
        style={{ transform: `translateY(${top}px)` }}
        onClick={() => onSelect(vm)}
        onKeyDown={(e) => {
          if (
            e.target === e.currentTarget &&
            (e.key === "Enter" || e.key === " ")
          ) {
            e.preventDefault();
            onSelect(vm);
          }
        }}
      >
        <div role="cell" className="ev-cell promo-info">
          <span className="ev-league">{vm.league}</span>
          <Matchup text={vm.matchup} sportKey={vm.sportKey} />
          <small>{vm.startsAt ? date(vm.startsAt) : ""}</small>
        </div>
        <div role="cell" className="ev-cell promo-leg">
          <span className="promo-tag">Promo · {vm.promo.bookLabel}</span>
          <small>{vm.market}</small>
          <strong>
            {vm.promo.label} <b>{vm.promo.odds}</b>
            {type === "boost" && c && (
              <b className="promo-boosted">
                {" → "}
                {american(c.boostedDecimal.toFixed(6))}
              </b>
            )}
          </strong>
        </div>
        <div role="cell" className="ev-cell promo-leg">
          <span className="promo-tag">Hedge · {vm.hedge.bookLabel}</span>
          <small>{vm.market}</small>
          <strong>
            {vm.hedge.label} <b>{vm.hedge.odds}</b>
          </strong>
          {c && (
            <span className="promo-hedge">
              Stake {money(c.hedge)}
              <CopyIconButton value={c.hedge.toFixed(2)} label="hedge stake" />
            </span>
          )}
          <Warnings
            hedge={c?.hedge ?? null}
            limit={limit}
            widthCents={vm.widthCents}
            boostCapped={!!c && (c.overMaxStake || c.capHit)}
          />
        </div>
        <div role="cell" className="ev-cell promo-type">
          <span className={`promo-badge type-${type}`}>{TYPE_NAME[type]}</span>
        </div>
        <div role="cell" className="ev-cell promo-effcell">
          <Efficiency rate={vm.rate} type={type} />
          <Age value={vm.observedAt} />
        </div>
        <div role="cell" className="ev-cell promo-act">
          <button
            type="button"
            className="button promo-go"
            onClick={(e) => {
              e.stopPropagation();
              onSelect(vm);
            }}
          >
            Calculate
          </button>
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
    a.boost === b.boost &&
    a.limit === b.limit &&
    a.top === b.top &&
    a.selected === b.selected,
);

function Steps({
  type,
  vm,
  c,
  face,
  rate,
  boost,
  onConvertVoucher,
}: {
  type: PromoType;
  vm: Vm;
  c: Conversion;
  face: number;
  rate: number;
  boost: Boost;
  onConvertVoucher: () => void;
}) {
  // The price the sportsbook shows on the boosted slip; c.boostedDecimal is the blend after any limits.
  const boosted = american(
    (1 + (vm.promo.decimal - 1) * (1 + boost.percent)).toFixed(6),
  );
  const place =
    type === "boost"
      ? `On ${vm.promo.bookLabel}, activate the boost, then place your cash bet of ${money(face)} on ${vm.promo.label}. The bet slip should show the boosted price (${vm.promo.odds} → ${boosted}) before you confirm.`
      : `On ${vm.promo.bookLabel}, place ${
          type === "nosweat"
            ? "your cash bet"
            : `your ${TYPE_NAME[type].toLowerCase()}`
        } of ${money(face)} on ${vm.promo.label} @ ${vm.promo.odds}.`;
  const hedge = `On ${vm.hedge.bookLabel}, place a ${money(c.hedge)} cash bet on ${vm.hedge.label} @ ${vm.hedge.odds}. Do this right away so the prices do not move.`;
  const loseNow = c.ifHedgeWins - c.voucherValue;
  return (
    <div className="promo-steps">
      <h4>Step by step</h4>
      <ol>
        <li>{place}</li>
        <li>{hedge}</li>
        {type === "nosweat" ? (
          <>
            <li>
              <strong>If {vm.promo.label} wins</strong>, collect on{" "}
              {vm.promo.bookLabel}. Your hedge loses, and you are up{" "}
              <b>{money(c.ifPromoWins)}</b> in cash. You are done.
            </li>
            <li>
              <strong>If {vm.promo.label} loses</strong>, your hedge on{" "}
              {vm.hedge.bookLabel} wins. For now you are{" "}
              {loseNow < 0 ? "down" : "up"} <b>{money(Math.abs(loseNow))}</b> in
              cash, and {vm.promo.bookLabel} refunds your {money(face)} stake as
              a bonus bet. Check the promo terms for when it arrives and when it
              expires.
            </li>
            <li>
              Convert the refunded bonus bet to cash: place it on an underdog
              (+200 to +500 works best) at {vm.promo.bookLabel}, and bet the
              other side with cash at the book offering the best price.{" "}
              <button
                type="button"
                className="link-button promo-link"
                onClick={onConvertVoucher}
              >
                Find bonus bet conversions for {money(face)}
              </button>
            </li>
            <li>
              At the {Math.round(rate * 100)}% voucher value you entered, that
              conversion returns about <b>{money(c.voucherValue)}</b>, bringing
              this path to <b>{money(c.ifHedgeWins)}</b>. If the bonus bet
              converts at a different rate, so does this total.
            </li>
          </>
        ) : type === "boost" ? (
          <>
            <li>
              <strong>If {vm.promo.label} wins</strong>, {vm.promo.bookLabel}{" "}
              returns your {money(face)} stake plus boosted winnings, a total of{" "}
              <b>{money(face * c.boostedDecimal)}</b>. Your hedge loses, and you
              are up <b>{money(c.ifPromoWins)}</b> after both stakes.
            </li>
            <li>
              <strong>If {vm.promo.label} loses</strong>, you lose your{" "}
              {money(face)} stake, but your hedge on {vm.hedge.bookLabel} wins
              and you are up <b>{money(c.ifHedgeWins)}</b> after both stakes.
            </li>
            {(c.overMaxStake || c.capHit) && (
              <li>
                <strong>The boost is limited:</strong>{" "}
                {c.overMaxStake
                  ? `only the first ${money(boost.maxStake ?? 0)} of your stake is boosted, and the rest pays normal odds. `
                  : ""}
                {c.capHit
                  ? `the extra winnings are held at ${money(boost.maxExtra ?? 0)}. `
                  : ""}
                The numbers above already count this. The price on your slip may
                show the full boost, so check the payout it shows.
              </li>
            )}
          </>
        ) : type === "bonus" ? (
          <>
            <li>
              <strong>If {vm.promo.label} wins</strong>, the bonus bet pays only
              its winnings, never the stake. Your hedge loses, and you are up{" "}
              <b>{money(c.ifPromoWins)}</b> in cash.
            </li>
            <li>
              <strong>If {vm.promo.label} loses</strong>, the bonus bet is gone,
              but it never cost you cash. Your hedge wins and you are up{" "}
              <b>{money(c.ifHedgeWins)}</b>.
            </li>
          </>
        ) : (
          <>
            <li>
              <strong>If {vm.promo.label} wins</strong>, the site credit pays
              its stake and winnings. Your hedge loses, and you are up{" "}
              <b>{money(c.ifPromoWins)}</b> in cash.
            </li>
            <li>
              <strong>If {vm.promo.label} loses</strong>, the credit is gone,
              but it never cost you cash. Your hedge wins and you are up{" "}
              <b>{money(c.ifHedgeWins)}</b>.
            </li>
          </>
        )}
      </ol>
    </div>
  );
}
function Calculator({
  vm,
  shift,
  onAccept,
  globalType,
  face,
  setFace,
  refund,
  setRefund,
  boostFields,
  setBoostFields,
  limit,
  onClose,
  onLogged,
  onConvertVoucher,
}: {
  vm: Vm | null;
  shift: "ok" | "moved" | "dropped";
  onAccept: () => void;
  globalType: PromoType;
  face: string;
  setFace: (v: string) => void;
  refund: string;
  setRefund: (v: string) => void;
  boostFields: BoostFields;
  setBoostFields: (b: BoostFields) => void;
  limit: number;
  onClose: () => void;
  onLogged: () => void;
  onConvertVoucher: (amount: string) => void;
}) {
  // The workspace previews any promo type without touching the list's filters.
  const [type, setType] = useState<PromoType>(globalType);
  useEffect(() => setType(globalType), [globalType, vm?.id]);
  useEffect(() => {
    if (!vm) return;
    const close = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [vm, onClose]);

  const valid = AMOUNT.test(face) && Number(face) > 0;
  const refundRate = PCT.test(refund)
    ? Math.min(Number(refund), 100) / 100
    : 0.75;
  const sig = vm?.sig ?? "";
  const boost = useMemo(() => toBoost(boostFields), [boostFields]);
  const c = useMemo(
    () =>
      vm && valid && (type !== "boost" || boostValid(boostFields))
        ? convert(
            type,
            Number(face),
            vm.promo.decimal,
            vm.hedge.decimal,
            refundRate,
            boost,
          )
        : null,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [sig, type, face, valid, refundRate, boost, boostFields],
  );
  const info = TYPES.find((t) => t.id === type)!;
  // Each promo type is recorded as what it really is: a free bet costs no cash, site credit also
  // pays its stake back on a win, a boost is a cash bet at the boosted price, and a risk-free bet
  // is a cash bet whose refund (if it loses) is logged later as a bonus bet.
  const stakeType =
    type === "bonus" ? "bonus" : type === "credit" ? "credit" : "cash";
  const context = (leg: Vm["promo"]) => ({
    matchup: vm!.matchup,
    book: leg.bookLabel,
    odds: leg.odds,
    strategy: "promo" as const,
    sportKey: vm!.sportKey,
    startsAt: vm!.startsAt,
    market: vm!.market,
    ref: leg.ref,
  });
  const logLegs: NewBet[] =
    vm && c && valid
      ? [
          {
            ...context(vm.promo),
            line: `${vm.promo.label} · ${info.name}`,
            stake: Number(face).toFixed(2),
            stakeType,
            ...(type === "boost" && {
              decimalOdds: c.boostedDecimal.toFixed(6),
            }),
            ...(type === "nosweat" && {
              notes: "Risk-free: if this loses, log the refund as a bonus bet.",
            }),
          },
          {
            ...context(vm.hedge),
            line: `Hedge · ${vm.hedge.label}`,
            stake: c.hedge.toFixed(2),
          },
        ]
      : [];
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
            <Matchup text={vm.matchup} sportKey={vm.sportKey} size={22} />
            <span>
              {vm.league} · {vm.market}
            </span>
            {c && <Efficiency rate={c.rate} type={type} />}
          </div>
          <div
            className="arb-modes promo-types"
            role="group"
            aria-label="Promo type"
          >
            {TYPES.map((t) => (
              <button
                key={t.id}
                type="button"
                className={type === t.id ? "active" : ""}
                aria-pressed={type === t.id}
                onClick={() => setType(t.id)}
              >
                {t.name}
              </button>
            ))}
          </div>
          <small className="kelly-note">
            {info.full}. {info.help}
          </small>
          <label className="field">
            <span>{sizeLabel(type)}</span>
            <input
              inputMode="decimal"
              value={face}
              maxLength={10}
              aria-invalid={!valid}
              onChange={(e) => setFace(e.target.value.trim())}
            />
          </label>
          {type === "nosweat" && (
            <label className="field">
              <span>VOUCHER VALUE · {PCT.test(refund) ? refund : "75"}%</span>
              <input
                inputMode="numeric"
                value={refund}
                maxLength={3}
                aria-invalid={!PCT.test(refund)}
                onChange={(e) => setRefund(e.target.value.trim())}
              />
              <small className="kelly-note">
                If the cash bet loses, you get its stake back as a bonus bet.
                This is the share of that refund you expect to turn into cash
                once you convert it (about 60–80%).
              </small>
            </label>
          )}
          {type === "boost" && (
            <>
              <label className="field">
                <span>
                  PROFIT BOOST ·{" "}
                  {BOOST_PCT.test(boostFields.percent)
                    ? boostFields.percent
                    : "—"}
                  %
                </span>
                <input
                  inputMode="decimal"
                  value={boostFields.percent}
                  maxLength={7}
                  aria-invalid={!BOOST_PCT.test(boostFields.percent)}
                  onChange={(e) =>
                    setBoostFields({
                      ...boostFields,
                      percent: e.target.value.trim(),
                    })
                  }
                />
                <small className="kelly-note">
                  The boost raises your winnings, not your stake. At +200 a 50%
                  boost pays like +300.
                </small>
              </label>
              <label className="field">
                <span>MAX BOOSTED STAKE ($) · BLANK = NO LIMIT</span>
                <input
                  inputMode="decimal"
                  value={boostFields.maxStake}
                  maxLength={10}
                  aria-invalid={!limitOk(boostFields.maxStake)}
                  onChange={(e) =>
                    setBoostFields({
                      ...boostFields,
                      maxStake: e.target.value.trim(),
                    })
                  }
                />
                <small className="kelly-note">
                  Stake above this pays at normal odds. Check the boost banner.
                </small>
              </label>
              <label className="field">
                <span>MAX EXTRA WINNINGS ($) · BLANK = NO CAP</span>
                <input
                  inputMode="decimal"
                  value={boostFields.maxExtra}
                  maxLength={10}
                  aria-invalid={!limitOk(boostFields.maxExtra)}
                  onChange={(e) =>
                    setBoostFields({
                      ...boostFields,
                      maxExtra: e.target.value.trim(),
                    })
                  }
                />
              </label>
            </>
          )}
          <div className="arb-stake">
            <span>
              {type === "nosweat" || type === "boost"
                ? "Place the cash bet"
                : "Place the promo"}{" "}
              on {vm.promo.bookLabel} · {vm.promo.label} @ {vm.promo.odds}
            </span>
            <output>{valid ? money(Number(face)) : "—"}</output>
            <span />
          </div>
          {!valid || !c ? (
            <p className="kelly-empty">
              {type === "boost" && !boostValid(boostFields)
                ? "Enter the boost percentage and valid limits."
                : "Enter an amount greater than zero."}
            </p>
          ) : (
            <>
              <div className="arb-stake">
                <span>
                  Cash hedge on {vm.hedge.bookLabel} · {vm.hedge.label} @{" "}
                  {vm.hedge.odds}
                </span>
                <output>{money(c.hedge)}</output>
                <CopyIconButton
                  value={c.hedge.toFixed(2)}
                  label="hedge stake"
                />
              </div>
              <Warnings
                hedge={c.hedge}
                limit={limit}
                widthCents={vm.widthCents}
                boostCapped={c.overMaxStake || c.capHit}
              />
              <div className="arb-summary">
                <span>Required hedge stake</span>
                <b>{money(c.hedge)}</b>
                <span>Total capital required</span>
                <b>{money(c.capital)}</b>
                <span>If {vm.promo.label} wins</span>
                <b>{money(c.ifPromoWins)}</b>
                <span>If {vm.hedge.label} wins</span>
                <b>{money(c.ifHedgeWins)}</b>
                <span>Guaranteed net cash return</span>
                <b className="arb-net">{money(c.profit)}</b>
                <span>
                  {type === "boost"
                    ? "Return on capital"
                    : "Conversion efficiency"}
                </span>
                <b>
                  <Efficiency rate={c.rate} type={type} />
                </b>
              </div>
              <LegLinks
                legs={[
                  {
                    links: vm.promo.links,
                    bookLabel: vm.promo.bookLabel,
                    label: vm.promo.label,
                    stake: Number(face).toFixed(2),
                  },
                  {
                    links: vm.hedge.links,
                    bookLabel: vm.hedge.bookLabel,
                    label: vm.hedge.label,
                    stake: c.hedge.toFixed(2),
                  },
                ]}
                startsAt={vm.startsAt}
                unavailable={shift === "dropped"}
              />
              <LogBetButton
                legs={logLegs}
                resetKey={`${vm.id}|${vm.sig}|${type}|${face}|${refund}|${JSON.stringify(boostFields)}`}
                onLogged={onLogged}
              />
              <Steps
                type={type}
                vm={vm}
                c={c}
                face={Number(face)}
                rate={refundRate}
                boost={boost}
                onConvertVoucher={() => onConvertVoucher(face)}
              />
            </>
          )}
        </>
      )}
    </aside>
  );
}

type PromoSettings = {
  type: string;
  face: string;
  refund: string;
  boost: BoostFields;
  limitText: string;
  promoBook: string;
  minOdds: string;
  maxOdds: string;
  minRate: string;
  sortKey: string;
  offBooks: string[];
  offSports: string[];
  offMarkets: string[];
};
const PROMO_DEFAULTS: PromoSettings = {
  type: "bonus",
  face: "100",
  refund: "75",
  boost: DEFAULT_BOOST,
  limitText: DEFAULT_HEDGE_LIMIT,
  promoBook: "",
  minOdds: DEFAULT_ODDS.bonus[0],
  maxOdds: DEFAULT_ODDS.bonus[1],
  minRate: "",
  sortKey: "rate",
  offBooks: [],
  offSports: [],
  offMarkets: [],
};

export default function PromoFeed({ data }: { data: Data }) {
  const { timeFilter, setTimeFilter, matchesTime } = useFeedTimeFilter();
  const [type, setType] = useState<PromoType>("bonus");
  const [face, setFace] = useState("100");
  const [refund, setRefund] = useState("75");
  const [boostFields, setBoostFields] = useState<BoostFields>(DEFAULT_BOOST);
  const [limitText, setLimitText] = useState(DEFAULT_HEDGE_LIMIT);
  const [promoBook, setPromoBook] = useState("");
  const [minOdds, setMinOdds] = useState(DEFAULT_ODDS.bonus[0]);
  const [maxOdds, setMaxOdds] = useState(DEFAULT_ODDS.bonus[1]);
  const [minRate, setMinRate] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("rate");
  const [offBooks, setOffBooks] = useState<Set<string>>(new Set());
  const [offSports, setOffSports] = useState<Set<string>>(new Set());
  const [offMarkets, setOffMarkets] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<Vm | null>(null);
  const {
    slip,
    open: slipOpen,
    setOpen: setSlipOpen,
    refresh: refreshSlip,
  } = useSlip();
  const settings = useToolSettings<PromoSettings>({
    tool: "promo",
    defaults: PROMO_DEFAULTS,
    snapshot: {
      type,
      face,
      refund,
      boost: boostFields,
      limitText,
      promoBook,
      minOdds,
      maxOdds,
      minRate,
      sortKey,
      offBooks: sorted(offBooks),
      offSports: sorted(offSports),
      offMarkets: sorted(offMarkets),
    },
    apply: (s) => {
      setType(
        choice(
          s.type,
          TYPES.map((t) => t.id),
          "bonus",
        ),
      );
      setFace(text(s.face, AMOUNT, PROMO_DEFAULTS.face));
      setRefund(text(s.refund, PCT, PROMO_DEFAULTS.refund));
      const boost = { ...DEFAULT_BOOST, ...(s.boost as Partial<BoostFields>) };
      setBoostFields(
        boostValid(boost)
          ? {
              percent: String(boost.percent),
              maxStake: String(boost.maxStake ?? ""),
              maxExtra: String(boost.maxExtra ?? ""),
            }
          : DEFAULT_BOOST,
      );
      setLimitText(text(s.limitText, AMOUNT, DEFAULT_HEDGE_LIMIT));
      setPromoBook(text(s.promoBook, /^[A-Za-z0-9_.-]{0,80}$/, ""));
      setMinOdds(text(s.minOdds, /^[-+]?\d{0,5}$/, PROMO_DEFAULTS.minOdds));
      setMaxOdds(text(s.maxOdds, /^[-+]?\d{0,5}$/, PROMO_DEFAULTS.maxOdds));
      setMinRate(text(s.minRate, /^(\d{1,3})?$/, ""));
      setSortKey(
        choice(
          s.sortKey,
          SORT_LABELS.map(([k]) => k),
          "rate",
        ),
      );
      setOffBooks(new Set(asList(s.offBooks)));
      setOffSports(new Set(asList(s.offSports)));
      setOffMarkets(new Set(asList(s.offMarkets)));
    },
    legacy: () => {
      const saved = JSON.parse(userStorage.getItem(SETTINGS_KEY) ?? "null");
      userStorage.removeItem(SETTINGS_KEY);
      return saved;
    },
  });
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
  const boost = useMemo(() => toBoost(boostFields), [boostFields]);
  const boostBad = type === "boost" && !boostValid(boostFields);
  const limit = hedgeLimit(limitText);
  const lowOdds = minOdds ? parseAmerican(minOdds) : null;
  const highOdds = maxOdds ? parseAmerican(maxOdds) : null;
  const rateLimit = PCT.test(minRate) ? Number(minRate) / 100 : null;
  const oddsBad =
    (minOdds !== "" && lowOdds === null) ||
    (maxOdds !== "" && highOdds === null);

  const all = useMemo(() => {
    if (!promoBook || boostBad) return [];
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
          boost,
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
          widthCents: marketWidthCents(d1, Number(best.decimal_odds)),
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
    boost,
    boostBad,
    lowOdds,
    highOdds,
    offBooks,
    offSports,
    offMarkets,
  ]);

  const visible = useMemo(
    () =>
      all
        .filter(
          (v) =>
            matchesTime(v.startsAt) &&
            (rateLimit === null || v.rate >= rateLimit),
        )
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
    [matchesTime, all, rateLimit, sortKey],
  );
  const byId = useMemo(() => new Map(all.map((v) => [v.id, v])), [all]);
  // Membership follows these settings, so changing one is not a data update.
  const changeScope = [
    promoBook,
    boostBad,
    minOdds,
    maxOdds,
    [...offBooks].sort().join(","),
    [...offSports].sort().join(","),
    [...offMarkets].sort().join(","),
  ].join("|");
  const promoIds = useMemo(
    () => (promoBook ? all.map((v) => v.id) : null),
    [all, promoBook],
  );
  const change = useFeedChanges(promoIds, changeScope);
  const avg = visible.length
    ? visible.reduce((s, v) => s + v.rate, 0) / visible.length
    : null;

  const [compact, setCompact] = useState(false);
  useEffect(() => {
    const media = matchMedia("(max-width:1380px)");
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
        <SettingsBar controls={settings} />
        <FeedTimeFilter value={timeFilter} onChange={setTimeFilter} />
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
          <span>{sizeLabel(type)}</span>
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
        {type === "boost" && (
          <>
            <label className="field mid-small">
              <span>PROFIT BOOST %</span>
              <input
                inputMode="decimal"
                value={boostFields.percent}
                maxLength={7}
                aria-invalid={!BOOST_PCT.test(boostFields.percent)}
                onChange={(e) =>
                  setBoostFields({
                    ...boostFields,
                    percent: e.target.value.trim(),
                  })
                }
              />
            </label>
            <label className="field mid-small">
              <span>MAX BOOSTED STAKE ($)</span>
              <input
                inputMode="decimal"
                placeholder="no limit"
                value={boostFields.maxStake}
                maxLength={10}
                aria-invalid={!limitOk(boostFields.maxStake)}
                onChange={(e) =>
                  setBoostFields({
                    ...boostFields,
                    maxStake: e.target.value.trim(),
                  })
                }
              />
            </label>
            <label className="field mid-small">
              <span>MAX EXTRA WINNINGS ($)</span>
              <input
                inputMode="decimal"
                placeholder="no cap"
                value={boostFields.maxExtra}
                maxLength={10}
                aria-invalid={!limitOk(boostFields.maxExtra)}
                onChange={(e) =>
                  setBoostFields({
                    ...boostFields,
                    maxExtra: e.target.value.trim(),
                  })
                }
              />
            </label>
          </>
        )}
        <label className="field mid-small">
          <span>{type === "boost" ? "MIN RETURN %" : "MIN CONVERSION %"}</span>
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
          <span>HEDGE LIMIT ($)</span>
          <input
            inputMode="decimal"
            value={limitText}
            maxLength={9}
            aria-invalid={!AMOUNT.test(limitText) || Number(limitText) <= 0}
            onChange={(e) => setLimitText(e.target.value.trim())}
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
            <SlipToggle
              count={slip.length}
              onClick={() => setSlipOpen((o) => !o)}
            />
            <strong>{visible.length}</strong> conversions · {help} Hedges are
            two-way markets only.
            <FeedChangeNote change={change} />
          </div>
          {slipOpen && <SlipLog slip={slip} onCleared={refreshSlip} />}
          <div
            role="table"
            aria-label="Promo conversions"
            className="ev-grid promo-grid"
          >
            <div role="row" className="ev-head">
              <span role="columnheader">Market</span>
              <span role="columnheader">Promo leg</span>
              <span role="columnheader">Hedge leg</span>
              <span role="columnheader">Promo type</span>
              <span role="columnheader">Efficiency</span>
              <span role="columnheader">Action</span>
            </div>
            {!promoBook ? (
              <div className="empty-state">
                <h3>Pick your promo sportsbook</h3>
                <p>
                  Choose the book that holds your bonus, then every game is
                  scanned for the best cash hedge at the other books.
                </p>
              </div>
            ) : boostBad ? (
              <div className="empty-state">
                <h3>Check the boost terms</h3>
                <p>
                  Enter the boost percentage, such as 50, and dollar limits or
                  leave a limit empty if the sportsbook sets none.
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
                      boost={boost}
                      limit={limit}
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
          globalType={type}
          face={face}
          setFace={setFace}
          refund={refund}
          setRefund={setRefund}
          boostFields={boostFields}
          setBoostFields={setBoostFields}
          onConvertVoucher={(amount) => {
            changeType("bonus");
            setFace(amount);
          }}
          limit={limit}
          onClose={() => setSelected(null)}
          onLogged={refreshSlip}
        />
      </div>
    </section>
  );
}

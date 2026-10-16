"use client";
import { useDialogFocus } from "./use-dialog-focus";
import { ParlayLegList } from "./parlay-tracker";
import { memo, useEffect, useMemo, useRef, useState } from "react";
import { american, americanToDecimal, usd } from "../../frontend/format.mjs";
import { splitMatchup } from "../lib/media";
import type {
  LiveView,
  NewBetBody,
  Result,
  Strategy,
  TrackerBet,
} from "../lib/tracker-api";
import {
  COMMON_BOOKS,
  LEAGUE_KEYS,
  STRATEGY_LABEL,
  bookAbbr,
  bookCode,
  bookLabel,
  cashOf,
  dollars,
  edgeFromProbability,
  kellyCents,
  leagueLabel,
  parseDollars,
  profit,
  signedDollars,
  signedPercent,
  sparkPath,
  toWin,
  type BookBalance,
  type Kpis,
} from "../lib/tracker-math";
import { Avatar } from "./media";

const amer = (decimal: string) => {
  try {
    return american(decimal);
  } catch {
    return decimal;
  }
};
const WHEN = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
  timeZone: "America/Chicago",
});
export const when = (iso: string | null) =>
  iso && !Number.isNaN(new Date(iso).getTime())
    ? WHEN.format(new Date(iso))
    : "—";
const money = (cents: number) => usd(dollars(cents));
const fmt = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1));

// ---- KPI ribbon -------------------------------------------------------------------------------

export function KpiRibbon({
  kpi,
  bankroll,
  pendingTotal,
}: {
  kpi: Kpis;
  bankroll: number;
  pendingTotal: number;
}) {
  const up = kpi.pnl >= 0;
  const spark = sparkPath(kpi.spark, 150, 34);
  return (
    <div className="trk-kpis" aria-label="Performance summary">
      <div className={`trk-kpi ${up ? "up" : "down"}`}>
        <span>NET P&amp;L</span>
        <strong className={up ? "pos" : "neg"}>{signedDollars(kpi.pnl)}</strong>
        {spark ? (
          <svg viewBox="0 0 150 34" aria-hidden="true" className="trk-spark">
            <path
              d={spark}
              fill="none"
              stroke={up ? "#10b981" : "#e11d48"}
              strokeWidth="2"
            />
          </svg>
        ) : (
          <small>Settle bets to draw a trend</small>
        )}
      </div>
      <div className="trk-kpi">
        <span>BANKROLL</span>
        <strong>{money(bankroll)}</strong>
        <small>{money(pendingTotal)} pending</small>
      </div>
      <div
        className={`trk-kpi ${kpi.roi == null ? "" : kpi.roi >= 0 ? "up" : "down"}`}
      >
        <span>ROI</span>
        <strong className={kpi.roi == null ? "" : kpi.roi >= 0 ? "pos" : "neg"}>
          {signedPercent(kpi.roi)}
        </strong>
        <small>
          {kpi.wins}-{kpi.losses}-{kpi.pushes} W-L-P
        </small>
      </div>
      <div className="trk-kpi">
        <span>CLV BEAT RATE</span>
        <strong>
          {kpi.clvBeat == null ? "—" : `${(kpi.clvBeat * 100).toFixed(1)}%`}
        </strong>
        <small>
          {kpi.clvMeasured
            ? `${signedPercent(kpi.clvAvg)} avg · ${kpi.clvMeasured} of ${kpi.clvTotal} measured`
            : "No closing lines measured yet"}
        </small>
      </div>
      <div className="trk-kpi">
        <span>OPEN BETS</span>
        <strong>{kpi.pending}</strong>
        <small>{money(kpi.pendingExposure)} at risk</small>
      </div>
    </div>
  );
}

// ---- ledger rows ------------------------------------------------------------------------------

function Bar({ progress }: { progress: NonNullable<LiveView["progress"]> }) {
  const { value, line, side } = progress;
  const ratio = line > 0 ? Math.min(1, value / line) : 0;
  const over = side === "over";
  const state =
    value > line
      ? over
        ? "cleared"
        : "busted"
      : value === line
        ? "even"
        : "open";
  return (
    <div className="trk-live">
      <div
        className={`trk-bar ${state}`}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={line}
        aria-valuenow={Math.min(value, line)}
        aria-label={`${fmt(value)} of ${fmt(line)}`}
      >
        <i style={{ width: `${ratio * 100}%` }} />
      </div>
      <span className="trk-mono">
        {fmt(value)} / {fmt(line)}
        {state === "cleared" && " ✓"}
        {state === "busted" && " ✕"}
      </span>
    </div>
  );
}

function pickedName(bet: TrackerBet): string | null {
  const ref = bet.ref;
  if (typeof ref.player === "string" && ref.player) return ref.player;
  if (ref.side === "home" && typeof ref.home === "string") return ref.home;
  if (ref.side === "away" && typeof ref.away === "string") return ref.away;
  return null;
}

export const BetRow = memo(function BetRow({
  bet,
  live,
  selected,
  onSelect,
  onApply,
}: {
  bet: TrackerBet;
  live: LiveView | undefined;
  selected: boolean;
  onSelect: (id: string) => void;
  onApply: (id: string, result: Result) => void;
}) {
  const p = profit(bet);
  const pending = bet.status === "pending";
  const name = pickedName(bet);
  const prop = typeof bet.ref.player === "string" && bet.ref.player;
  const showLive = pending && live && live.state !== "pre";
  const clock =
    pending && live
      ? live.state === "in"
        ? live.detail
        : live.state === "post"
          ? "Final"
          : ""
      : "";
  const away = typeof bet.ref.away === "string" ? bet.ref.away : "";
  const home = typeof bet.ref.home === "string" ? bet.ref.home : "";
  const clv = bet.clv?.pct == null ? null : Number(bet.clv.pct);
  return (
    <tr
      className={`trk-row ${selected ? "selected" : ""}`}
      tabIndex={0}
      aria-selected={selected}
      onClick={() => onSelect(bet.id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(bet.id);
        }
      }}
    >
      <td className="trk-event">
        <span className="trk-when">{when(bet.starts_at ?? bet.placed_at)}</span>
        <span className="trk-match">{bet.matchup}</span>
        <small>{leagueLabel(bet.sport_key)}</small>
      </td>
      <td className="trk-c-book" data-label="Book">
        <span className="trk-book" title={bookLabel(bet.book)}>
          {bookAbbr(bet.book)}
        </span>
      </td>
      <td className="trk-c-strat" data-label="Strategy">
        <span className={`trk-strat s-${bet.strategy}`}>
          {STRATEGY_LABEL[bet.strategy] ?? bet.strategy}
        </span>
      </td>
      <td className="trk-sel">
        <div className="trk-sel-box">
          <div className="trk-sel-top">
            {name && (
              <Avatar
                kind={prop ? "player" : "team"}
                name={name}
                sportKey={bet.sport_key}
                size={26}
              />
            )}
            <span className="trk-title">{bet.selection}</span>
            {clock && <span className="trk-clock trk-mono">{clock}</span>}
          </div>
          {showLive && live.progress ? (
            <Bar progress={live.progress} />
          ) : showLive && live.state !== "unknown" ? (
            <span className="trk-score trk-mono">
              {away} {live.score.away ?? "–"} · {home} {live.score.home ?? "–"}
            </span>
          ) : pending && live?.state === "unknown" ? (
            <span className="trk-muted">
              Live tracking unavailable for this game
            </span>
          ) : !pending ? (
            <span className="trk-muted">Settled {when(bet.settled_at)}</span>
          ) : null}
          {pending && live?.suggest && (
            <button
              type="button"
              className={`trk-suggest ${live.suggest.result}`}
              title={live.suggest.basis}
              onClick={(e) => {
                e.stopPropagation();
                onApply(bet.id, live.suggest!.result);
              }}
            >
              Final · looks like {live.suggest.result.toUpperCase()} — apply
            </button>
          )}
        </div>
      </td>
      <td className="trk-num" data-label="Odds">
        <b>{amer(bet.odds)}</b>
        {bet.stake_type !== "cash" && (
          <small className="trk-free">
            {bet.stake_type === "bonus" ? "BONUS BET" : "SITE CREDIT"}
          </small>
        )}
      </td>
      <td className="trk-num" data-label="Stake">
        <b>{money(bet.stake_cents)}</b>
        <small>{pending ? `to win ${money(toWin(bet))}` : ""}</small>
      </td>
      <td className="trk-num" data-label="Result">
        {pending ? (
          <span className="trk-chip pending">Open</span>
        ) : (
          <>
            <b
              className={
                p != null && p > 0 ? "pos" : p != null && p < 0 ? "neg" : ""
              }
            >
              {p == null ? "—" : signedDollars(p)}
            </b>
            <small className={`trk-res ${bet.status}`}>{bet.status}</small>
          </>
        )}
      </td>
      <td className="trk-num" data-label="CLV" title={bet.clv?.reason}>
        <b
          className={clv == null ? "" : clv > 0 ? "pos" : clv < 0 ? "neg" : ""}
        >
          {clv == null ? "—" : signedPercent(clv)}
        </b>
      </td>
    </tr>
  );
});

// ---- filter menu ------------------------------------------------------------------------------

// A multi-select where "nothing ticked" means everything.
export function PickMenu({
  title,
  items,
  picked,
  onChange,
}: {
  title: string;
  items: [string, string][];
  picked: string[];
  onChange: (next: string[]) => void;
}) {
  return (
    <details className="arb-menu">
      <summary>
        {title} ({picked.length ? picked.length : "all"})
      </summary>
      <div className="arb-menu-pop">
        <div>
          <button
            type="button"
            className="link-button"
            onClick={() => onChange([])}
          >
            all
          </button>
        </div>
        {items.map(([id, label]) => (
          <label key={id}>
            <input
              type="checkbox"
              checked={picked.includes(id)}
              onChange={() =>
                onChange(
                  picked.includes(id)
                    ? picked.filter((p) => p !== id)
                    : [...picked, id],
                )
              }
            />
            {label}
          </label>
        ))}
        {items.length === 0 && <small>None yet.</small>}
      </div>
    </details>
  );
}

// ---- drawers ----------------------------------------------------------------------------------

function useDrawerKeys(open: boolean, onClose: () => void) {
  useEffect(() => {
    if (!open) return;
    const close = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [open, onClose]);
}

function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const run = async (work: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await work();
    } catch (e) {
      setError(e instanceof Error ? e.message : "That did not work.");
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, run, clear: () => setError("") };
}

const RESULTS: [Result, string][] = [
  ["won", "Won"],
  ["lost", "Lost"],
  ["push", "Push"],
  ["void", "Void"],
];

export function BetDrawer({
  bet,
  live,
  siblings,
  onClose,
  onSettle,
  onReopen,
  onDelete,
  onUpdate,
}: {
  bet: TrackerBet | null;
  live: LiveView | undefined;
  siblings: TrackerBet[];
  onClose: () => void;
  onSettle: (id: string, result: Result, returned?: string) => Promise<void>;
  onReopen: (id: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  onUpdate: (id: string, changes: Record<string, unknown>) => Promise<void>;
}) {
  useDrawerKeys(!!bet, onClose);
  const act = useAction();
  const [cashout, setCashout] = useState("");
  const [odds, setOdds] = useState("");
  const [stake, setStake] = useState("");
  const [book, setBook] = useState("");
  const [notes, setNotes] = useState("");
  const id = bet?.id;
  useEffect(() => {
    if (!bet) return;
    setCashout("");
    setOdds(amer(bet.odds));
    setStake(dollars(bet.stake_cents));
    setBook(bookLabel(bet.book));
    setNotes(bet.notes);
    act.clear();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);
  const p = bet ? profit(bet) : null;
  const save = () =>
    act.run(async () => {
      if (!bet) return;
      const sign = /^[+-]/.test(odds.trim()) ? odds.trim() : `+${odds.trim()}`;
      const cents = parseDollars(stake);
      if (cents == null || cents <= 0)
        throw new Error("Enter the stake as dollars, such as 25 or 25.50.");
      await onUpdate(bet.id, {
        odds: americanToDecimal(sign),
        stake: dollars(cents),
        book: bookCode(book),
        notes,
      });
    });
  const dialogRef = useDialogFocus(Boolean(bet));
  return (
    <aside
      ref={dialogRef}
      role="dialog"
      aria-modal={Boolean(bet) ? true : undefined}
      aria-hidden={!Boolean(bet)}
      className={`kelly-panel trk-drawer ${bet ? "open" : ""}`}
      aria-label="Bet details"
    >
      <button className="kelly-close" onClick={onClose} aria-label="Close">
        ✕
      </button>
      <h3>Bet details</h3>
      {!bet ? (
        <p className="kelly-empty">Select a bet to see it here.</p>
      ) : (
        <>
          <div className="kelly-head">
            <strong>{bet.matchup}</strong>
            <span>{bet.selection}</span>
            <small>
              {bookLabel(bet.book)} @ {amer(bet.odds)} ·{" "}
              {money(bet.stake_cents)}
              {bet.stake_type !== "cash"
                ? ` ${bet.stake_type === "bonus" ? "bonus bet" : "site credit"}`
                : ""}
            </small>
          </div>
          {bet.status !== "pending" && (
            <div className="trk-result-box">
              <span className={`trk-res ${bet.status}`}>{bet.status}</span>
              <strong
                className={
                  p != null && p > 0 ? "pos" : p != null && p < 0 ? "neg" : ""
                }
              >
                {p == null ? "—" : signedDollars(p)}
              </strong>
              <small>returned {money(bet.returned_cents ?? 0)}</small>
            </div>
          )}
          <ParlayLegList bet={bet} onUpdate={onUpdate} />
          {live && bet.status === "pending" && live.state !== "pre" && (
            <div className="trk-live-box">
              <strong>
                {live.state === "post" ? "Final" : live.detail || "In progress"}
              </strong>
              {live.progress && (
                <span className="trk-mono">
                  {fmt(live.progress.value)} / {fmt(live.progress.line)}
                </span>
              )}
              {live.suggest && (
                <button
                  className="button kelly-bet"
                  disabled={act.busy}
                  onClick={() =>
                    act.run(() => onSettle(bet.id, live.suggest!.result))
                  }
                >
                  Apply suggested result: {live.suggest.result.toUpperCase()}
                </button>
              )}
              {live.suggest && (
                <small className="kelly-note">
                  {live.suggest.basis}. Check it against the sportsbook before
                  applying.
                </small>
              )}
            </div>
          )}
          <div className="trk-facts">
            <span>Market</span>
            <b>{bet.market || "—"}</b>
            <span>League</span>
            <b>{leagueLabel(bet.sport_key)}</b>
            <span>Strategy</span>
            <b>{STRATEGY_LABEL[bet.strategy]}</b>
            <span>Placed</span>
            <b>{when(bet.placed_at)}</b>
            <span>Game time</span>
            <b>{when(bet.starts_at)}</b>
            <span>To win</span>
            <b>{money(toWin(bet))}</b>
            {bet.ev_ratio != null && (
              <>
                <span>Edge at bet</span>
                <b>{signedPercent(Number(bet.ev_ratio))}</b>
              </>
            )}
            <span>Closing value</span>
            <b>
              {bet.clv?.pct != null
                ? `${signedPercent(Number(bet.clv.pct))}${bet.clv.close_odds ? ` (close ${amer(bet.clv.close_odds)})` : ""}`
                : (bet.clv?.reason ?? "Measured after the game starts")}
            </b>
          </div>
          <div
            className="trk-actions"
            role="group"
            aria-label={bet.status === "pending" ? "Settle" : "Change result"}
          >
            <span className="trk-sub">
              {bet.status === "pending" ? "SETTLE THIS BET" : "CHANGE RESULT"}
            </span>
            <div className="trk-seg">
              {RESULTS.map(([r, label]) => (
                <button
                  key={r}
                  type="button"
                  className={`${r} ${bet.status === r ? "active" : ""}`}
                  disabled={act.busy || bet.status === r}
                  onClick={() =>
                    act.run(() =>
                      onSettle(
                        bet.id,
                        r,
                        bet.legs?.length && r === "won" && cashout
                          ? cashout
                          : undefined,
                      ),
                    )
                  }
                >
                  {label}
                </button>
              ))}
            </div>
            <label className="field">
              <span>
                {bet.legs?.length
                  ? "ACTUAL RETURN / CASHOUT ($)"
                  : "OR CASHED OUT FOR ($)"}
              </span>
              <div className="trk-inline">
                <input
                  inputMode="decimal"
                  value={cashout}
                  placeholder="0.00"
                  onChange={(e) => setCashout(e.target.value)}
                />
                <button
                  type="button"
                  className="button secondary"
                  disabled={act.busy || parseDollars(cashout) == null}
                  onClick={() =>
                    act.run(() =>
                      onSettle(
                        bet.id,
                        "cashout",
                        cashout.trim().replace(/^\$/, ""),
                      ),
                    )
                  }
                >
                  Cash out
                </button>
              </div>
            </label>
            {bet.status !== "pending" && (
              <button
                type="button"
                className="button secondary"
                disabled={act.busy}
                onClick={() => act.run(() => onReopen(bet.id))}
              >
                Reopen as pending
              </button>
            )}
          </div>
          {siblings.length > 0 && (
            <div className="trk-group">
              <span className="trk-sub">OTHER LEGS OF THIS PLAY</span>
              {siblings.map((s) => (
                <div key={s.id}>
                  <span>{s.selection}</span>
                  <small>
                    {bookLabel(s.book)} · {money(s.stake_cents)} · {s.status}
                  </small>
                </div>
              ))}
            </div>
          )}
          <details className="trk-edit">
            <summary>Correct this bet</summary>
            <label className="field">
              <span>SPORTSBOOK</span>
              <input
                value={book}
                list="trk-books"
                onChange={(e) => setBook(e.target.value)}
              />
            </label>
            <label className="field">
              <span>ODDS (AMERICAN)</span>
              <input value={odds} onChange={(e) => setOdds(e.target.value)} />
            </label>
            <label className="field">
              <span>STAKE ($)</span>
              <input
                inputMode="decimal"
                value={stake}
                onChange={(e) => setStake(e.target.value)}
              />
            </label>
            <label className="field">
              <span>NOTES</span>
              <input
                value={notes}
                maxLength={500}
                onChange={(e) => setNotes(e.target.value)}
              />
            </label>
            <button
              type="button"
              className="button secondary"
              disabled={act.busy}
              onClick={save}
            >
              Save changes
            </button>
            {bet.status !== "pending" && (
              <small className="kelly-note">
                The payout is recalculated from the saved odds and stake.
              </small>
            )}
          </details>
          {act.error && (
            <div role="alert" className="arb-alert">
              <span>{act.error}</span>
            </div>
          )}
          <button
            type="button"
            className="trk-danger"
            disabled={act.busy}
            onClick={() => {
              if (
                window.confirm(
                  "Delete this bet from your ledger? This cannot be undone.",
                )
              )
                act.run(() => onDelete(bet.id));
            }}
          >
            Delete bet
          </button>
        </>
      )}
    </aside>
  );
}

// ---- log a bet --------------------------------------------------------------------------------

const SCALARS: [string, string][] = [
  ["0.25", "Quarter Kelly"],
  ["0.5", "Half Kelly"],
  ["1", "Full Kelly"],
];

export function LogDrawer({
  open,
  rows,
  bankroll,
  hasCash,
  onClose,
  onSubmit,
}: {
  open: boolean;
  rows: BookBalance[];
  bankroll: number;
  hasCash: boolean;
  onClose: () => void;
  onSubmit: (bets: NewBetBody[]) => Promise<void>;
}) {
  useDrawerKeys(open, onClose);
  const act = useAction();
  const attempt = useRef(crypto.randomUUID());
  const [matchup, setMatchup] = useState("");
  const [selection, setSelection] = useState("");
  const [league, setLeague] = useState("");
  const [starts, setStarts] = useState("");
  const [book, setBook] = useState("");
  const [strategy, setStrategy] = useState<Strategy>("manual");
  const [stakeType, setStakeType] = useState<"cash" | "bonus" | "credit">(
    "cash",
  );
  const [odds, setOdds] = useState("");
  const [stake, setStake] = useState("");
  const [notes, setNotes] = useState("");
  const [basis, setBasis] = useState("total");
  const [scalar, setScalar] = useState("0.25");
  const [winPct, setWinPct] = useState("");

  const dec = useMemo(() => {
    const t = odds.trim();
    if (!/^[+-]?\d{3,5}$/.test(t)) return null;
    try {
      return Number(americanToDecimal(/^[+-]/.test(t) ? t : `+${t}`));
    } catch {
      return null;
    }
  }, [odds]);
  const prob = /^\d{1,2}(\.\d{1,2})?$/.test(winPct)
    ? Number(winPct) / 100
    : null;
  const edge =
    prob != null && dec != null ? edgeFromProbability(prob, dec) : null;
  const available = basis === "total" ? bankroll : cashOf(rows, bookCode(book));
  const suggested =
    edge != null && dec != null
      ? kellyCents(edge, dec, available, Number(scalar))
      : 0;

  const submit = () =>
    act.run(async () => {
      if (!matchup.trim())
        throw new Error("Enter the event, such as Celtics at Heat.");
      if (!selection.trim())
        throw new Error("Enter what you bet on, such as Celtics -3.5.");
      if (!book.trim()) throw new Error("Choose the sportsbook.");
      if (dec == null)
        throw new Error("Enter American odds such as +110 or -125.");
      const cents = parseDollars(stake);
      if (cents == null || cents <= 0)
        throw new Error("Enter the stake as dollars, such as 25 or 25.50.");
      const sides = splitMatchup(matchup.trim());
      let startsAt: string | undefined;
      if (starts) {
        const d = new Date(starts);
        if (Number.isNaN(d.getTime()))
          throw new Error("The start time is not valid.");
        startsAt = d.toISOString();
      }
      const t = odds.trim();
      await onSubmit([
        {
          client_key: `ui:${attempt.current}`,
          strategy,
          matchup: sides ? `${sides[0]} at ${sides[1]}` : matchup.trim(),
          selection: selection.trim(),
          book: bookCode(book),
          odds: americanToDecimal(/^[+-]/.test(t) ? t : `+${t}`),
          stake: dollars(cents),
          sport_key: league,
          starts_at: startsAt ?? null,
          stake_type: stakeType,
          fair_prob: prob != null ? String(prob) : null,
          ev_ratio: edge != null ? edge.toFixed(6) : null,
          notes: notes.trim(),
          ref: sides ? { away: sides[0], home: sides[1] } : {},
        },
      ]);
      attempt.current = crypto.randomUUID();
      setMatchup("");
      setSelection("");
      setOdds("");
      setStake("");
      setNotes("");
      setWinPct("");
    });

  const dialogRef = useDialogFocus(open);
  return (
    <aside
      ref={dialogRef}
      role="dialog"
      aria-modal={open ? true : undefined}
      aria-hidden={!open}
      className={`kelly-panel trk-drawer ${open ? "open" : ""}`}
      aria-label="Log a bet"
    >
      <button className="kelly-close" onClick={onClose} aria-label="Close">
        ✕
      </button>
      <h3>Log a bet</h3>
      <small className="kelly-note">
        Record a bet you placed at a sportsbook. Nothing is placed from here.
      </small>
      <label className="field">
        <span>EVENT</span>
        <input
          value={matchup}
          placeholder="Celtics at Heat"
          maxLength={200}
          onChange={(e) => setMatchup(e.target.value)}
        />
      </label>
      <label className="field">
        <span>SELECTION</span>
        <input
          value={selection}
          placeholder="Jayson Tatum Over 5.5 REB"
          maxLength={200}
          onChange={(e) => setSelection(e.target.value)}
        />
      </label>
      <label className="field">
        <span>LEAGUE</span>
        <select value={league} onChange={(e) => setLeague(e.target.value)}>
          <option value="">Other / not listed</option>
          {LEAGUE_KEYS.map((k) => (
            <option key={k} value={k}>
              {leagueLabel(k)}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>GAME START (OPTIONAL)</span>
        <input
          type="datetime-local"
          value={starts}
          onChange={(e) => setStarts(e.target.value)}
        />
      </label>
      <label className="field">
        <span>SPORTSBOOK</span>
        <input
          value={book}
          list="trk-books"
          placeholder="FanDuel"
          onChange={(e) => setBook(e.target.value)}
        />
      </label>
      <label className="field">
        <span>STRATEGY</span>
        <select
          value={strategy}
          onChange={(e) => setStrategy(e.target.value as Strategy)}
        >
          {Object.entries(STRATEGY_LABEL)
            .filter(([k]) => k !== "parlay")
            .map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
        </select>
      </label>
      <label className="field">
        <span>STAKE TYPE</span>
        <select
          value={stakeType}
          onChange={(e) => setStakeType(e.target.value as typeof stakeType)}
        >
          <option value="cash">Cash</option>
          <option value="bonus">Bonus bet (free stake, winnings only)</option>
          <option value="credit">Site credit (paid out with the stake)</option>
        </select>
      </label>
      <label className="field">
        <span>ODDS (AMERICAN)</span>
        <input
          value={odds}
          placeholder="+110"
          inputMode="numeric"
          onChange={(e) => setOdds(e.target.value)}
          aria-invalid={odds !== "" && dec == null}
        />
      </label>

      <div className="trk-kelly">
        <span className="trk-sub">KELLY SIZING</span>
        <label className="field">
          <span>YOUR WIN PROBABILITY (%)</span>
          <input
            inputMode="decimal"
            value={winPct}
            placeholder="e.g. 54"
            onChange={(e) => setWinPct(e.target.value)}
          />
        </label>
        <div className="trk-two">
          <label className="field">
            <span>SCALAR</span>
            <select value={scalar} onChange={(e) => setScalar(e.target.value)}>
              {SCALARS.map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>BANKROLL</span>
            <select value={basis} onChange={(e) => setBasis(e.target.value)}>
              <option value="total">Total</option>
              <option value="book">This book</option>
            </select>
          </label>
        </div>
        <div className="trk-suggestion">
          {!hasCash ? (
            <small>
              Add a deposit on the Bankroll tab to size against your real
              bankroll.
            </small>
          ) : edge == null ? (
            <small>Enter odds and your win probability.</small>
          ) : edge <= 0 ? (
            <small>
              No edge at these odds ({signedPercent(edge)}), so Kelly suggests
              no bet.
            </small>
          ) : (
            <>
              <strong>{money(suggested)}</strong>
              <small>
                {available > 0
                  ? `${((suggested / available) * 100).toFixed(2)}% of ${money(Math.max(0, available))} · edge ${signedPercent(edge)}`
                  : "No available bankroll"}
              </small>
              <button
                type="button"
                className="button secondary"
                disabled={suggested <= 0}
                onClick={() => setStake(dollars(suggested))}
              >
                Use this stake
              </button>
            </>
          )}
        </div>
      </div>

      <label className="field">
        <span>STAKE ($)</span>
        <input
          inputMode="decimal"
          value={stake}
          placeholder="25.00"
          onChange={(e) => setStake(e.target.value)}
        />
      </label>
      <label className="field">
        <span>NOTES (OPTIONAL)</span>
        <input
          value={notes}
          maxLength={500}
          onChange={(e) => setNotes(e.target.value)}
        />
      </label>
      {act.error && (
        <div role="alert" className="arb-alert">
          <span>{act.error}</span>
        </div>
      )}
      <button className="button kelly-bet" disabled={act.busy} onClick={submit}>
        {act.busy ? "Saving…" : "Log bet"}
      </button>
    </aside>
  );
}

export function BookList({ codes }: { codes: string[] }) {
  const all = useMemo(
    () => [...new Set([...COMMON_BOOKS, "vault", ...codes])],
    [codes],
  );
  return (
    <datalist id="trk-books">
      {all.map((c) => (
        <option key={c} value={bookLabel(c)} />
      ))}
    </datalist>
  );
}

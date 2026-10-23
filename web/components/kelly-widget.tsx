"use client";
import { useEffect } from "react";
import { Icon } from "./icon";
import { useDialogFocus } from "./use-dialog-focus";
import {
  compareDecimal,
  subDecimal,
  mulDecimal,
  divDecimal,
  fixed,
  percent,
  usd,
} from "../../frontend/format.mjs";
import type { QuoteLinks } from "../lib/bet-links";
import type { RefValue, Strategy } from "../lib/tracker-api";
import type { NewBet } from "../lib/slip";
import { userStorage } from "../lib/user-storage";
import { bookCode, bookLabel, dollars } from "../lib/tracker-math";
import { useTrackedBankroll, LogBetButton } from "./bet-slip";
import { usePlaced, PlacedNoteFor } from "./placed";
import { Matchup, Avatar } from "./media";
import { BetLinkButton } from "./bet-link";
export interface KellyVm {
  netDecimalOdds?: string;
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
  excludesDraw?: boolean;
  // What the tracker records about the bet; absent for views that only size a stake.
  strategy?: Strategy;
  startsAt?: string;
  fairProb?: string;
  ref?: Record<string, RefValue>;
  // Where to open this exact bet at the sportsbook.
  links?: QuoteLinks | null;
}

export const BANKROLL_KEY = "corner.bankroll";
export const MULTIPLIER_KEY = "corner.kelly";
export type SizingSettings = { bankroll: string; multiplier: string };
export const SIZING_DEFAULTS: SizingSettings = {
  bankroll: "1000",
  multiplier: "0.25",
};
// Bankroll and multiplier kept in this browser before they moved to the account (used once).
export function legacySizing(): Partial<SizingSettings> | null {
  const bankroll = userStorage.getItem(BANKROLL_KEY);
  const multiplier = userStorage.getItem(MULTIPLIER_KEY);
  userStorage.removeItem(BANKROLL_KEY);
  userStorage.removeItem(MULTIPLIER_KEY);
  return bankroll || multiplier
    ? {
        ...(bankroll && { bankroll }),
        ...(multiplier && { multiplier }),
      }
    : null;
}

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

export function KellyWidget({
  vm,
  bankroll,
  setBankroll,
  multiplier,
  setMultiplier,
  onClose,
  onLogged,
  unavailable = false,
}: {
  onLogged: () => void;
  // The update that just ran dropped this bet: show it as gone and do not allow logging it.
  unavailable?: boolean;
  vm: KellyVm | null;
  bankroll: string;
  setBankroll: (v: string) => void;
  multiplier: string;
  setMultiplier: (v: string) => void;
  onClose: () => void;
}) {
  const tracked = useTrackedBankroll();
  const placed = usePlaced(vm ? [vm] : []).placed > 0;
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
      ? kelly(
          vm.ev,
          vm.netDecimalOdds ?? vm.decimalOdds,
          bankroll,
          multiplier,
          vm.lay,
        )
      : null;
  const legs: NewBet[] =
    vm && result
      ? [
          {
            matchup: vm.matchup,
            line: vm.line,
            book: vm.bookLabel,
            odds: vm.odds,
            stake: fixed(result.stake, 2),
            strategy: vm.strategy ?? (vm.player ? "prop" : "ev"),
            sportKey: vm.sportKey,
            startsAt: vm.startsAt,
            market: vm.market,
            decimalOdds: vm.netDecimalOdds ?? vm.decimalOdds,
            notes:
              vm.netDecimalOdds && vm.netDecimalOdds !== vm.decimalOdds
                ? "Net modeled odds after commission; confirm actual book settlement."
                : undefined,
            fairProb: vm.fairProb,
            evRatio: vm.ev,
            ref: vm.ref,
          },
        ]
      : [];
  const trackedDollars = tracked.ready ? dollars(tracked.bankroll) : "";
  const bookCash = vm ? tracked.liquid(bookCode(vm.bookLabel)) : null;
  const stakeCents = result ? Math.round(Number(result.stake) * 100) : 0;
  const dialogRef = useDialogFocus(Boolean(vm));
  return (
    <aside
      ref={dialogRef}
      role="dialog"
      aria-modal={vm ? true : undefined}
      aria-hidden={!vm}
      className={`kelly-panel ${vm ? "open" : ""}`}
      aria-label="Kelly calculator"
    >
      <button className="kelly-close" onClick={onClose} aria-label="Close">
        <Icon name="close" />
      </button>
      <h3>Kelly calculator</h3>
      {!vm ? (
        <p className="kelly-empty">Select a row to size the bet.</p>
      ) : (
        <>
          {unavailable && (
            <div role="alert" className="arb-alert">
              <strong>This bet is no longer available.</strong>
              <span>
                The latest update dropped it. The numbers below are its last
                prices.
              </span>
            </div>
          )}
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
            {tracked.ready &&
              tracked.bankroll > 0 &&
              trackedDollars !== bankroll && (
                <button
                  type="button"
                  className="trk-link"
                  onClick={() => setBankroll(trackedDollars)}
                >
                  Use tracked bankroll ({usd(trackedDollars)})
                </button>
              )}
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
          {bookCash != null && result && stakeCents > bookCash && (
            <small className="kelly-note" role="alert">
              Your tracked {bookLabel(bookCode(vm.bookLabel))} balance is{" "}
              {usd(dollars(Math.max(0, bookCash)))}, less than this stake. Move
              cash there first.
            </small>
          )}
          <BetLinkButton
            links={vm.links}
            bookLabel={vm.bookLabel}
            stake={result ? fixed(result.stake, 2) : undefined}
            startsAt={vm.startsAt}
            unavailable={unavailable}
          />
          <PlacedNoteFor leg={vm} />
          <LogBetButton
            placed={placed}
            legs={legs}
            resetKey={vm.id}
            disabled={!result || unavailable}
            onLogged={onLogged}
          />
        </>
      )}
    </aside>
  );
}

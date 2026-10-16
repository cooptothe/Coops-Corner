"use client";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { date, usd } from "../../frontend/format.mjs";
import { importLegacySlip, logBets, onLogged, type NewBet } from "../lib/slip";
import { loadTracker, type TrackerBet } from "../lib/tracker-api";
import {
  bookBalances,
  bookLabel,
  cashOf,
  dollars,
  totals,
} from "../lib/tracker-math";

// The tracked net bankroll, so the Kelly drawer can size against real money. `ready` is false until
// the tracker has any cash entries (a bankroll of zero would mean "nothing deposited", not "broke").
export function useTrackedBankroll() {
  const [info, setInfo] = useState<{
    ready: boolean;
    bankroll: number;
    rows: ReturnType<typeof bookBalances>;
  }>({ ready: false, bankroll: 0, rows: [] });
  const [version, setVersion] = useState(0);
  useEffect(() => onLogged(() => setVersion((n) => n + 1)), []);
  useEffect(() => {
    let live = true;
    loadTracker().then(
      (state) => {
        if (!live) return;
        const rows = bookBalances(state);
        setInfo({
          ready: state.cash.length > 0,
          bankroll: totals(rows).bankroll,
          rows,
        });
      },
      () => live && setInfo({ ready: false, bankroll: 0, rows: [] }),
    );
    return () => {
      live = false;
    };
  }, [version]);
  return {
    ready: info.ready,
    bankroll: info.bankroll,
    // Cash currently available at a book, or null when nothing has been tracked yet.
    liquid: (code: string) => (info.ready ? cashOf(info.rows, code) : null),
  };
}

// The pending bets in the tracker, kept fresh whenever any tool logs one.
export function useSlip() {
  const [slip, setSlip] = useState<TrackerBet[]>([]);
  const [open, setOpen] = useState(false);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let live = true;
    importLegacySlip()
      .then(() => loadTracker())
      .then((state) => {
        if (live)
          setSlip(state.bets.filter((b) => b.status === "pending").reverse());
      })
      .catch(() => live && setSlip([]));
    return () => {
      live = false;
    };
  }, [version]);
  const refresh = useCallback(() => setVersion((n) => n + 1), []);
  useEffect(() => onLogged(refresh), [refresh]);
  return { slip, open, setOpen, refresh };
}

export function SlipToggle({
  count,
  onClick,
}: {
  count: number;
  onClick: () => void;
}) {
  return (
    <button className="button secondary ev-slip-toggle" onClick={onClick}>
      Open bets ({count})
    </button>
  );
}

export function SlipLog({
  slip,
}: {
  slip: TrackerBet[];
  onCleared?: () => void;
}) {
  return (
    <div className="ev-slip">
      {slip.length === 0 ? (
        <p>No open bets. Select a bet and use Record bet to track it.</p>
      ) : (
        <table>
          <tbody>
            {slip.slice(0, 12).map((b) => (
              <tr key={b.id}>
                <td>{date(b.placed_at)}</td>
                <td>
                  {b.matchup} · {b.selection}
                </td>
                <td>{bookLabel(b.book)}</td>
                <td>{usd(dollars(b.stake_cents))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <Link className="button secondary" href="/tracker">
        Open the tracker
      </Link>
    </div>
  );
}

// Records every leg of the open play in the tracker. `resetKey` re-arms the button for a new bet.
// The button only says "Logged" once the ledger has confirmed the save.
export function LogBetButton({
  legs,
  resetKey,
  disabled,
  placed = false,
  onLogged: after,
}: {
  legs: NewBet[];
  resetKey: string;
  disabled?: boolean;
  // This bet is already in the tracker; the button says so instead of inviting a duplicate.
  placed?: boolean;
  onLogged?: () => void;
}) {
  const [state, setState] = useState<"idle" | "pending" | "done" | "error">(
    "idle",
  );
  const [error, setError] = useState("");
  const sig = useMemo(() => JSON.stringify(legs), [legs]);
  // A new attempt id per distinct play: retrying the same legs after a failure cannot double-record.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const attempt = useMemo(() => crypto.randomUUID(), [sig, resetKey]);
  useEffect(() => setState("idle"), [sig, resetKey]);
  const place = () => {
    if (!legs.length) return;
    setState("pending");
    setError("");
    logBets(legs, attempt).then(
      () => {
        setState("done");
        after?.();
      },
      (e: unknown) => {
        setError(e instanceof Error ? e.message : "Could not save the bet.");
        setState("error");
      },
    );
  };
  return (
    <>
      <button
        className="button kelly-bet"
        disabled={disabled || !legs.length || state === "pending"}
        onClick={place}
      >
        {state === "pending"
          ? "Recording…"
          : state === "done"
            ? "Logged ✓"
            : state === "error"
              ? "Try again"
              : placed
                ? "Already placed · log again"
                : legs.length > 1
                  ? "Record all legs"
                  : "Record bet"}
      </button>
      {state === "error" ? (
        <small className="kelly-note" role="alert">
          {error}
        </small>
      ) : (
        <small className="kelly-note">
          {state === "done" ? (
            <>
              Recorded in your tracker. Review the accepted odds and stake
              against your sportsbook receipt.{" "}
              <Link href="/tracker">Open tracker</Link>
            </>
          ) : (
            "Record this after placing it at the sportsbook. No wager is placed here."
          )}
        </small>
      )}
    </>
  );
}

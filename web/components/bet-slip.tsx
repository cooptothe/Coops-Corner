"use client";
import { useCallback, useEffect, useState } from "react";
import { date, usd } from "../../frontend/format.mjs";
import {
  clearSlip,
  logBets,
  readSlip,
  type NewSlipBet,
  type SlipBet,
} from "../lib/slip";

export function useSlip() {
  const [slip, setSlip] = useState<SlipBet[]>([]);
  const [open, setOpen] = useState(false);
  const [version, setVersion] = useState(0);
  useEffect(() => setSlip(readSlip()), [version]);
  const refresh = useCallback(() => setVersion((n) => n + 1), []);
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
      My bets ({count})
    </button>
  );
}

export function SlipLog({
  slip,
  onCleared,
}: {
  slip: SlipBet[];
  onCleared: () => void;
}) {
  return (
    <div className="ev-slip">
      {slip.length === 0 ? (
        <p>No bets logged yet. Select a bet and use One-click bet.</p>
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
              clearSlip();
              onCleared();
            }}
          >
            Clear log
          </button>
        </>
      )}
    </div>
  );
}

// Logs every leg of the open play to "My bets" after the same short pending
// beat the Kelly calculator uses. `resetKey` re-arms the button for a new bet.
export function LogBetButton({
  legs,
  resetKey,
  disabled,
  onLogged,
}: {
  legs: NewSlipBet[];
  resetKey: string;
  disabled?: boolean;
  onLogged: () => void;
}) {
  const [state, setState] = useState<"idle" | "pending" | "done">("idle");
  useEffect(() => setState("idle"), [resetKey]);
  const place = () => {
    if (!legs.length) return;
    setState("pending");
    setTimeout(() => {
      logBets(legs);
      setState("done");
      onLogged();
    }, 700);
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
            : legs.length > 1
              ? "One-click bet (all legs)"
              : "One-click bet"}
      </button>
      <small className="kelly-note">
        {state === "done"
          ? "Saved to the local slip only. Nothing was placed at the sportsbook — place it there and re-check the price."
          : "Simulated: records the bet locally. It does not place a wager."}
      </small>
    </>
  );
}

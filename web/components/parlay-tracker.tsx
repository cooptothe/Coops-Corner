"use client";
import { useState } from "react";
import { american } from "../../frontend/format.mjs";
import type { TrackerBet } from "../lib/tracker-api";

export function ParlayLegList({
  bet,
  onUpdate,
}: {
  bet: TrackerBet;
  onUpdate: (id: string, changes: Record<string, unknown>) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!bet.legs?.length) return null;
  return (
    <section aria-label="Parlay legs">
      <h4>{bet.legs.length} legs · one wager</h4>
      <ol className="parlay-tracked-legs">
        {bet.legs.map((leg) => (
          <li key={leg.key}>
            <strong>{leg.selection}</strong>
            <div>{leg.matchup}</div>
            <small>
              {leg.market} · {american(leg.odds)} ·{" "}
              {leg.source === "prop" ? "Player prop" : "Main line"}
            </small>
            <div
              className="parlay-leg-status"
              role="group"
              aria-label={`Result for ${leg.selection}`}
            >
              {["pending", "won", "lost", "push", "void"].map((status) => (
                <button
                  key={status}
                  type="button"
                  className="button secondary"
                  aria-pressed={(leg.status ?? "pending") === status}
                  disabled={busy || bet.status !== "pending"}
                  onClick={async () => {
                    setBusy(true);
                    setError("");
                    try {
                      await onUpdate(bet.id, {
                        parlay_leg_key: leg.key,
                        parlay_leg_result: status,
                      });
                    } catch (e) {
                      setError(
                        e instanceof Error
                          ? e.message
                          : "The leg could not be updated.",
                      );
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  {status}
                </button>
              ))}
            </div>
          </li>
        ))}
      </ol>
      {bet.suggested_result && bet.status === "pending" && (
        <p>
          Leg results suggest: <strong>{bet.suggested_result}</strong>. Confirm
          the sportsbook's final result below.
        </p>
      )}
      {bet.legs.some((l) => l.status === "push" || l.status === "void") && (
        <p>
          For a winning parlay with pushed or voided legs, enter the
          sportsbook's actual returned amount.
        </p>
      )}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}

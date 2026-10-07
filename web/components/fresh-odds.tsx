"use client";
import { useEffect, useState } from "react";
import { reloadTools, refreshOdds, refreshStatus } from "../lib/refresh-api";
import type { RefreshStatus } from "../lib/refresh-api";

const STORAGE = "corner.refresh.leagues";

// Fetches fresh pre-game odds (spends credits), then rebuilds the tools from the database.
export default function FreshOdds({
  onRefreshed,
}: {
  onRefreshed: () => void;
}) {
  const [status, setStatus] = useState<RefreshStatus | null>(null);
  const [leagues, setLeagues] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE) ?? "null");
      if (Array.isArray(saved)) setLeagues(saved.map(String));
    } catch {
      /* ignore unreadable preference */
    }
    const controller = new AbortController();
    refreshStatus(controller.signal)
      .then(setStatus)
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  const chosen = leagues ?? status?.sports.map((s) => s.key) ?? [];
  const choose = (next: string[]) => {
    setLeagues(next);
    localStorage.setItem(STORAGE, JSON.stringify(next));
  };

  async function fetchFresh() {
    if (
      !chosen.length ||
      !window.confirm(
        `Fetch fresh pre-game odds for ${chosen.length} league(s) and recalculate all opportunities? Each in-season league costs 3 API credits (up to ${chosen.length * 3}); out-of-season leagues are free.`,
      )
    )
      return;
    setBusy(true);
    setError("");
    setNote("");
    try {
      const next = await refreshOdds(chosen);
      setStatus(next);
      const updated = Object.values(next.last_results ?? {}).filter(
        (r) => r === "ok",
      ).length;
      setNote(
        updated
          ? `Updated ${updated} league(s); opportunities recalculated.`
          : "No leagues had upcoming games to update.",
      );
      await reloadTools();
      onRefreshed();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Refresh failed.");
      refreshStatus()
        .then(setStatus)
        .catch(() => undefined);
      // The service may have finished even if the response was lost; re-read the database.
      await reloadTools();
      onRefreshed();
    } finally {
      setBusy(false);
    }
  }

  const wait = status?.retry_after_seconds ?? 0;
  return (
    <div className="fresh-odds">
      <button
        className="button"
        disabled={busy || !chosen.length || status?.can_refresh === false}
        onClick={fetchFresh}
        title="Calls The Odds API (uses credits), then recalculates every tool"
      >
        {busy ? "Fetching odds…" : "↻ Refresh odds"}
      </button>
      <details className="fresh-odds-menu">
        <summary>Leagues ({chosen.length})</summary>
        <div className="fresh-odds-panel">
          {status?.sports.map((s) => (
            <label key={s.key}>
              <input
                type="checkbox"
                checked={chosen.includes(s.key)}
                disabled={busy}
                onChange={() =>
                  choose(
                    chosen.includes(s.key)
                      ? chosen.filter((k) => k !== s.key)
                      : [...chosen, s.key],
                  )
                }
              />{" "}
              {s.label}
            </label>
          ))}
          <div>
            <button
              type="button"
              className="button secondary small"
              onClick={() => choose(status?.sports.map((s) => s.key) ?? [])}
            >
              All
            </button>{" "}
            <button
              type="button"
              className="button secondary small"
              onClick={() => choose([])}
            >
              None
            </button>
          </div>
          {status && (
            <small>
              Last fetch:{" "}
              {status.last_success_at
                ? new Date(status.last_success_at).toLocaleString()
                : "never"}
              {status.quota?.["x-requests-remaining"] &&
                ` · ${status.quota["x-requests-remaining"]} credits left`}
              {` · ${status.attempts_today}/${status.daily_cap} fetches today`}
              {wait > 0 && ` · next in ${Math.ceil(wait / 60)} min`}
            </small>
          )}
        </div>
      </details>
      {(error || status?.last_error || note) && (
        <p
          className={
            error || status?.last_error ? "fresh-odds-error" : "fresh-odds-note"
          }
          role={error || status?.last_error ? "alert" : "status"}
        >
          {error || status?.last_error || note}
        </p>
      )}
    </div>
  );
}

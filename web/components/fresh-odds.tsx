"use client";
import { useEffect, useState } from "react";
import { userStorage } from "../lib/user-storage";
import { reloadTools, refreshOdds, refreshStatus } from "../lib/refresh-api";
import type { RefreshStatus } from "../lib/refresh-api";
import { useDialogFocus } from "./use-dialog-focus";

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
  const [confirming, setConfirming] = useState(false);
  const reviewRef = useDialogFocus(confirming);
  useEffect(() => {
    if (!confirming) return;
    const close = (event: KeyboardEvent) =>
      event.key === "Escape" && setConfirming(false);
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [confirming]);

  useEffect(() => {
    try {
      const saved = JSON.parse(userStorage.getItem(STORAGE) ?? "null");
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

  // The cooldown is only known when the status was read, so read it again once it ends;
  // otherwise the button stays disabled until the page is reloaded.
  useEffect(() => {
    const wait = status?.retry_after_seconds ?? 0;
    if (wait <= 0) return;
    const timer = setTimeout(
      () =>
        refreshStatus()
          .then(setStatus)
          .catch(() => undefined),
      wait * 1000 + 300,
    );
    return () => clearTimeout(timer);
  }, [status]);

  const chosen = leagues ?? status?.sports.map((s) => s.key) ?? [];
  const choose = (next: string[]) => {
    setLeagues(next);
    userStorage.setItem(STORAGE, JSON.stringify(next));
  };

  async function fetchFresh() {
    if (!chosen.length || busy || status?.manual_fetch_enabled !== true) return;
    setConfirming(false);
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
      await reloadTools().catch(() => undefined);
      onRefreshed();
    } finally {
      setBusy(false);
    }
  }

  const wait = status?.retry_after_seconds ?? 0;
  if (status?.manual_fetch_enabled !== true)
    return <span className="muted">Scheduled collection</span>;
  return (
    <div className="fresh-odds">
      <button
        className="button"
        disabled={busy || !chosen.length || status?.can_refresh === false}
        onClick={() => setConfirming(true)}
        title={
          status?.can_refresh === false
            ? "Refresh is currently unavailable. Open Leagues for the last fetch and available details."
            : "Fetch updated odds for your selected leagues. This uses API credits."
        }
      >
        {busy ? "Fetching odds…" : "↻ Refresh odds"}
      </button>
      {confirming && (
        <div
          className="refresh-review-backdrop"
          onClick={() => setConfirming(false)}
        >
          <section
            className="refresh-review"
            ref={reviewRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="refresh-review-title"
            onClick={(event) => event.stopPropagation()}
          >
            <p className="eyebrow">UPDATE YOUR FEEDS</p>
            <h2 id="refresh-review-title">Refresh odds?</h2>
            <p>
              Fetch the latest pre-game odds for{" "}
              <strong>
                {chosen.length} selected{" "}
                {chosen.length === 1 ? "league" : "leagues"}
              </strong>
              . All tools will use the updated prices.
            </p>
            <div className="refresh-cost">
              <span>Base cost, plus event markets</span>
              <strong>
                {chosen.length * (status?.credits_per_sport ?? 6)} API credits
              </strong>
            </div>
            <p className="muted">
              Includes six additional markets for every upcoming game returned
              per league, at up to 12 extra credits per game. Tennis tournaments
              count separately and can increase the cost. Out-of-season leagues
              use no credits; filtering stored results is free.
            </p>
            <div className="refresh-review-actions">
              <button
                type="button"
                className="button secondary"
                onClick={() => setConfirming(false)}
              >
                Cancel
              </button>
              <button type="button" className="button" onClick={fetchFresh}>
                Refresh {chosen.length === 1 ? "league" : "leagues"}
              </button>
            </div>
          </section>
        </div>
      )}
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

"use client";
import { useEffect, useMemo, useState } from "react";
import { useAuth } from "./auth-provider";
import dynamic from "next/dynamic";
import { Loading } from "./feedback";
export { LiveSwitch } from "./live-switch";
const EvFeed = dynamic(() => import("./ev-feed"), {
  loading: () => <Loading text="Opening live EV…" />,
});
const ArbFeed = dynamic(() => import("./arb-feed"), {
  loading: () => <Loading text="Opening live arbitrage…" />,
});
const MiddleFeed = dynamic(() => import("./middle-feed"), {
  loading: () => <Loading text="Opening live middles…" />,
});
import {
  liveFresh,
  liveProduct,
  type LiveFeed as Feed,
  type LiveKind,
} from "../lib/live-feed";
import "../app/live-feed.css";
export default function PremiumLiveFeed({ kind }: { kind: LiveKind }) {
  const { user } = useAuth();
  const premium = user?.username.toLowerCase() === "wonya";
  const [feed, setFeed] = useState<Feed | null>(null),
    [error, setError] = useState("");
  const [method, setMethod] = useState("current"),
    [status, setStatus] = useState("");
  const [received, setReceived] = useState(0),
    [clock, setClock] = useState(0);
  useEffect(() => {
    if (!premium) return;
    let alive = true;
    let inFlight = false;
    let controller: AbortController | null = null;
    const load = async () => {
      if (document.hidden || inFlight) return;
      inFlight = true;
      controller?.abort();
      const current = new AbortController();
      controller = current;
      const timeout = setTimeout(() => current.abort(), 10000);
      try {
        const response = await fetch(
          `/api/v1/live-stoppages?devig_method=${encodeURIComponent(method)}`,
          {
            credentials: "same-origin",
            cache: "no-store",
            signal: current.signal,
          },
        );
        const body = await response.json();
        if (!response.ok)
          throw new Error(body.error || "Live feed unavailable.");
        if (body.format !== "corner.live_odds/1" || !Array.isArray(body.events))
          throw new Error("Unsupported live response.");
        if (alive) {
          setFeed(body);
          setReceived(Date.now());
          setClock(Date.now());
          setError("");
        }
      } catch (e) {
        if (alive) {
          setError(e instanceof Error ? e.message : "Live feed unavailable.");
          setFeed(null);
        }
      } finally {
        clearTimeout(timeout);
        inFlight = false;
      }
    };
    void load();
    const onVisible = () => {
      if (!document.hidden) void load();
    };
    document.addEventListener("visibilitychange", onVisible);
    const timer = setInterval(() => void load(), 15000),
      tick = setInterval(() => setClock(Date.now()), 1000);
    return () => {
      alive = false;
      document.removeEventListener("visibilitychange", onVisible);
      controller?.abort();
      clearInterval(timer);
      clearInterval(tick);
    };
  }, [premium, method]);

  const expired =
    feed?.events
      .flatMap((e) =>
        e.opportunities
          .filter((c) => !liveFresh(c, feed.as_of, clock - received))
          .map((c) => c.row_id),
      )
      .join("|") ?? "";
  const product = useMemo(
    () => (feed ? liveProduct(feed, status, clock - received) : null),
    [feed, status, expired],
  );
  const events =
    feed?.events.filter((e) => !status || e.status === status) ?? [];
  if (!premium)
    return (
      <section className="live-premium-gate">
        <h2>Live is a Premium feature</h2>
        <p>
          Premium access is currently limited to wonya. Turn Live off to return
          to pregame.
        </p>
      </section>
    );
  return (
    <section className="live-feed" aria-label="Premium live main lines">
      <div
        className="live-status-tabs"
        role="group"
        aria-label="Line availability"
      >
        {[
          ["", "All games"],
          ["active", "▶ Lines open"],
          ["no_active_lines", "Ⅱ No active lines"],
        ].map(([value, label]) => (
          <button
            key={value}
            type="button"
            className={status === value ? "button" : "button secondary"}
            aria-pressed={status === value}
            onClick={() => setStatus(value)}
          >
            {label}
          </button>
        ))}
      </div>
      <p className="live-summary" role="status">
        {error ||
          (!feed
            ? "Loading live odds…"
            : !feed.enabled
              ? "Live collection is not enabled yet."
              : `${events.length} games · ${feed.state.replaceAll("_", " ")} · collection every 60 seconds`)}
      </p>
      <details className="live-explainer">
        <summary>Live game availability ({events.length})</summary>
        <p>
          ▶ Lines open · Ⅱ No active lines. These signals describe bookmaker
          availability, not confirmed game stoppages. Quotes expire after 90
          seconds. Prices and settlement rules can change before acceptance.
        </p>
        <ul className="live-game-statuses">
          {events.map((e) => (
            <li key={`${e.sport_key}:${e.id}`}>
              <span>
                {e.status === "active"
                  ? "▶"
                  : e.status === "no_active_lines"
                    ? "Ⅱ"
                    : "—"}
              </span>
              <span>
                {e.away_team} at {e.home_team}
              </span>
              <small>
                {e.status === "active"
                  ? "Lines open"
                  : e.status === "no_active_lines"
                    ? "No active lines"
                    : "Awaiting fresh odds"}
              </small>
            </li>
          ))}
        </ul>
      </details>
      {product &&
        (kind === "ev" ? (
          <EvFeed
            data={product.data}
            liveRows={product.rows}
            liveMethod={feed?.devig_method ?? "current"}
            onLiveMethod={setMethod}
          />
        ) : kind === "arbitrage" ? (
          <ArbFeed data={product.data} liveRows={product.rows} />
        ) : (
          <MiddleFeed data={product.data} liveRows={product.rows} />
        ))}
    </section>
  );
}

"use client";
import { useEffect, useMemo, useState } from "react";
import { useUiBoolean } from "./use-ui-boolean";
import { Icon } from "./icon";
import { LiveBetLinks } from "./bet-link";
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
  EMPTY_LIVE_FEED,
  gameState,
  matchesLiveState,
  liveFresh,
  liveProduct,
  type LiveFeed as Feed,
  type LiveKind,
} from "../lib/live-feed";
import "../app/live-feed.css";
export default function PremiumLiveFeed({ kind }: { kind: LiveKind }) {
  const { user } = useAuth();
  const gamePanel = useUiBoolean(`live-game-status.${kind}`, true);
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
        if (!response.ok) {
          if (response.status === 401 || response.status === 403) setFeed(null);
          throw new Error(body.error || "Live feed unavailable.");
        }
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
  const serverNow = feed
    ? Date.parse(feed.as_of) / 1000 + (clock - received) / 1000
    : 0;
  const statusExpiry =
    feed?.events.map((e) => `${e.id}:${gameState(e, serverNow)}`).join("|") ??
    "";
  const product = useMemo(
    () => liveProduct(feed ?? EMPTY_LIVE_FEED, status, clock - received),
    [feed, status, expired, statusExpiry],
  );
  const events =
    feed?.events.filter((e) => matchesLiveState(e, status, serverNow)) ?? [];
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
    <LiveBetLinks.Provider value={true}>
      <section className="live-feed" aria-label="Premium live main lines">
        <div className="live-status-tabs" role="group" aria-label="Game state">
          {[
            ["", "All games"],
            ["playing", "Play"],
            ["paused", "Pause"],
          ].map(([value, label]) => (
            <button
              key={value}
              type="button"
              className={status === value ? "button" : "button secondary"}
              aria-pressed={status === value}
              aria-label={label}
              title={label}
              onClick={() => setStatus(value)}
            >
              {value === "playing" && <Icon name="play" />}
              {value === "paused" && <Icon name="pause" />}
              {!value && <Icon name="grid" />}
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
        <details
          className="live-explainer"
          open={gamePanel.value}
          onToggle={(event) => {
            const next = event.currentTarget.open;
            if (gamePanel.ready && next !== gamePanel.value)
              gamePanel.setValue(next);
          }}
        >
          <summary>Game status ({events.length})</summary>
          <ul className="live-game-statuses">
            {events.map((e) => (
              <li key={`${e.sport_key}:${e.id}`}>
                <span className="live-game-indicator" aria-hidden="true">
                  {gameState(e, serverNow) === "paused" ? (
                    <Icon name="pause" />
                  ) : gameState(e, serverNow) === "in_play" ? (
                    <Icon name="play" />
                  ) : (
                    <Icon name="clock" />
                  )}
                </span>
                <span>
                  {e.away_team} at {e.home_team}
                </span>
                <div className="live-game-detail">
                  <strong>
                    {gameState(e, serverNow) === "unknown"
                      ? "Game status unavailable"
                      : e.game_status_detail}
                  </strong>
                  <small>
                    {gameState(e, serverNow) !== "unknown" ? "ESPN · " : ""}
                    {e.status === "active"
                      ? "Odds available"
                      : e.status === "no_active_lines"
                        ? "No sportsbook lines"
                        : "Awaiting fresh odds"}
                  </small>
                </div>
              </li>
            ))}
          </ul>
        </details>
        {kind === "ev" ? (
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
        )}
      </section>
    </LiveBetLinks.Provider>
  );
}

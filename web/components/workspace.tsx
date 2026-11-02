"use client";
import { useUiBoolean } from "./use-ui-boolean";
import { Icon } from "./icon";
import type { ReactNode } from "react";
import Link from "next/link";
import Image from "next/image";
import dynamic from "next/dynamic";
import { ErrorCard, Loading } from "./feedback";
export { ErrorCard, Loading } from "./feedback";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  MARKETS,
  TITLES,
  date,
  sport,
  decimalInput,
  shiftDecimal,
} from "../../frontend/format.mjs";
import { ApiError, request, sharedPages } from "../lib/api";
import { loadSnapshotQuotes } from "../lib/snapshot-quotes";
import { loadToolSnapshot } from "../lib/tool-snapshot";
import { subscribeOddsUpdated } from "../lib/odds-updates";
import { reloadToolsOnce } from "../lib/refresh-api";
import type {
  View,
  Capabilities,
  Game,
  Quote,
  ToolRow,
  Meta,
  Page,
} from "../lib/contracts";
import { NavigationLinks } from "./navigation-links";
import { UserMenu, useAuth } from "./auth-provider";
import { Cards, Details, OddsMatrix } from "./market-views";
const PromoFeed = dynamic(() => import("./promo-feed"), {
  loading: () => <Loading text="Opening tool…" />,
});
const EvFeed = dynamic(() => import("./ev-feed"), {
  loading: () => <Loading text="Opening tool…" />,
});
const ArbFeed = dynamic(() => import("./arb-feed"), {
  loading: () => <Loading text="Opening tool…" />,
});
const MiddleFeed = dynamic(() => import("./middle-feed"), {
  loading: () => <Loading text="Opening tool…" />,
});
const ScheduleFeed = dynamic(() => import("./schedule-feed"), {
  loading: () => <Loading text="Opening tool…" />,
});
const PropsFeed = dynamic(() => import("./props-feed"), {
  loading: () => <Loading text="Opening tool…" />,
});
import FreshOdds from "./fresh-odds";
import { FeedGuide } from "./feed-guide";
import { LiveSwitch } from "./live-switch";
const PremiumLiveFeed = dynamic(() => import("./live-feed"), {
  loading: () => <Loading text="Opening live feed…" />,
});

const DESCRIPTIONS: Record<View, string> = {
  positive_ev:
    "Find prices above a reference-book estimate, then review the bet and your stake.",
  arbitrage:
    "Compare both sides of a market and see the stake and payoff for each leg.",
  middle:
    "Find cross-line windows. See the upside and the cost of missing the middle.",
  props:
    "Compare player props with reference prices and find bets that fit your filters.",
  games:
    "Upcoming games by day, with the best main-line spread, total and moneyline available.",
  promo:
    "Compare bonus offers, calculate a hedge, and see the cash you could receive.",
};
const ICONS: Record<View, ReactNode> = {
  positive_ev: <Icon name="trend" />,
  arbitrage: <Icon name="exchange" />,
  middle: <Icon name="middle" />,
  props: <Icon name="player" />,
  games: <Icon name="calendar" />,
  promo: <Icon name="promo" />,
};
type Data = { caps: Capabilities; games: Game[]; quotes: Quote[]; meta: Meta };
type Filters = {
  sport_key?: string;
  market_key?: string;
  sportsbook_id?: string;
  game_id?: string;
  search?: string;
  threshold?: string;
  sort?: string;
};
const isEv = (view: View): boolean =>
  view === "positive_ev" ||
  view === "arbitrage" ||
  view === "middle" ||
  view === "props" ||
  view === "games";
// The row list each feed loads for itself (shared with it through sharedPages, so it is only fetched once).
const ROW_LISTS: Partial<Record<View, string>> = {
  positive_ev: "tools/positive_ev",
  arbitrage: "tools/arbitrage",
  middle: "tools/middle",
};
const errorText = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "An unexpected request error occurred.";
export default function Workspace({ view }: { view: View }) {
  const router = useRouter();
  const navigation = useRef<HTMLElement>(null);
  useEffect(() => {
    if (matchMedia("(max-width: 700px)").matches)
      navigation.current
        ?.querySelector<HTMLElement>('[aria-current="page"]')
        ?.scrollIntoView({ block: "nearest", inline: "center" });
  }, [view]);
  const { user } = useAuth();
  const livePreference = useUiBoolean(`live-mode.${view}`, false);
  const liveMode = livePreference.value;
  const setLiveMode = livePreference.setValue;
  const supportsLive =
    view === "positive_ev" || view === "arbitrage" || view === "middle";
  const showingLive = supportsLive && liveMode;
  const loadedSnapshot = useRef<string | null>(null);
  const [scheduledTick, setScheduledTick] = useState(0);
  const [data, setData] = useState<Data | null>(null),
    [bootError, setBootError] = useState(""),
    [reload, setReload] = useState(0),
    [updating, setUpdating] = useState(false);
  useEffect(
    () => subscribeOddsUpdated(() => setReload((value) => value + 1)),
    [],
  );
  const [filters, setFilters] = useState<Filters>({}),
    [offset, setOffset] = useState(0),
    [limit, setLimit] = useState(10),
    [page, setPage] = useState<Page<ToolRow | Game> | null>(null),
    [pageError, setPageError] = useState(""),
    [pageLoading, setPageLoading] = useState(false),
    [retry, setRetry] = useState(0),
    [detail, setDetail] = useState<ToolRow | null>(null),
    [filterOpen, setFilterOpen] = useState(true),
    [stake, setStake] = useState("100"),
    [bankroll, setBankroll] = useState("1000");
  useEffect(() => {
    setFilters({});
    setOffset(0);
    setDetail(null);
    setPage(null);
  }, [view]);
  useEffect(() => {
    document.title = `${TITLES[view]} — The Corner`;
  }, [view]);
  useEffect(() => {
    const media = matchMedia("(max-width:600px)");
    const change = () => setFilterOpen(!media.matches);
    change();
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, []);
  // The props feed brings its own data, so for it only the small capabilities call is made, and it is shown at once.
  const light = view === "props";
  // Reads retained snapshots only. Background tabs and an in-flight load do not
  // start another poll; local non-beta use keeps its manual-fetch workflow.
  useEffect(() => {
    if (showingLive || !user?.role || updating) return;
    let timer: ReturnType<typeof setTimeout>;
    const later = () => {
      timer = setTimeout(() => {
        if (document.hidden) later();
        else setScheduledTick((value) => value + 1);
      }, 15000);
    };
    later();
    return () => clearTimeout(timer);
  }, [user?.role, updating, scheduledTick, showingLive]);
  useEffect(() => {
    // Props owns its authenticated data endpoint; main catalog rebuilds must
    // never delay or replace it with an unrelated catalog error.
    if (light) {
      setUpdating(false);
      setBootError("");
      return;
    }
    if ((supportsLive && !livePreference.ready) || showingLive) {
      setUpdating(false);
      return;
    }
    const controller = new AbortController();
    // Keep the current data on screen while an update loads: clearing it would unmount the
    // feed, close an open calculator and lose scroll position. The new data replaces it at once.
    if (scheduledTick === 0) setDetail(null);
    setBootError("");
    setUpdating(true);
    (async () => {
      try {
        // Scheduled catalogs already refresh on read; avoid a forced rebuild on page load.
        // Local manual mode retains its explicit reload, and manual fetches publish separately.
        if (!user?.role && !light) await reloadToolsOnce();
        if (controller.signal.aborted) return;
        const caps = await request<Capabilities>("capabilities", {
          signal: controller.signal,
        });
        if (
          loadedSnapshot.current ===
          `${user?.id}|${view}|${light}|${caps.meta.snapshot_id}`
        )
          return;
        if (light) {
          if (!controller.signal.aborted) {
            loadedSnapshot.current = `${user?.id}|${view}|${light}|${caps.meta.snapshot_id}`;
            setData({
              caps: caps.data,
              games: [],
              quotes: [],
              meta: caps.meta,
            });
          }
          return;
        }
        const snapshot = caps.meta.snapshot_id;
        // The feed's own rows are the slowest part after the quotes; start them now instead of when the feed mounts.
        const rows = ROW_LISTS[view];
        if (rows)
          loadToolSnapshot(
            view as "positive_ev" | "arbitrage" | "middle",
            snapshot,
            controller.signal,
          ).catch(() => undefined);
        const [games, quotes] = await Promise.all([
          sharedPages<Game>("games", snapshot, controller.signal),
          rows
            ? Promise.resolve([] as Quote[])
            : loadSnapshotQuotes(
                snapshot,
                controller.signal,
                caps.data.books,
                view === "games",
              ),
        ]);
        // Keep the order the quotes always had: by game, in the games' own order.
        const rank = new Map(games.map((g, i) => [g.id, i]));
        quotes.sort(
          (a, b) =>
            (rank.get(a.game_id) ?? games.length) -
            (rank.get(b.game_id) ?? games.length),
        );
        if (!controller.signal.aborted) {
          loadedSnapshot.current = `${user?.id}|${view}|${light}|${snapshot}`;
          setData({ caps: caps.data, games, quotes, meta: caps.meta });
        }
      } catch (error) {
        if (!controller.signal.aborted) setBootError(errorText(error));
      } finally {
        if (!controller.signal.aborted) setUpdating(false);
      }
    })();
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    reload,
    light,
    scheduledTick,
    showingLive,
    user?.id,
    livePreference.ready,
    view,
  ]);
  useEffect(() => {
    if (!data || view === "promo" || isEv(view)) return;
    const controller = new AbortController();
    setPageLoading(true);
    setPage(null);
    setPageError("");
    const params: Record<string, string | number | boolean | undefined> = {
      limit,
      offset,
      snapshot_id: data.meta.snapshot_id,
      sport_key: filters.sport_key,
      market_key: filters.market_key,
      sort:
        filters.sort ??
        (view === "games"
          ? "starts_at"
          : view === "positive_ev"
            ? "conditional_ev_ratio"
            : "minimum_profit"),
    };
    if (view === "games") params.search = filters.search;
    else {
      params.sportsbook_id = filters.sportsbook_id;
      params.game_id = filters.game_id;
    }
    params.descending = ["conditional_ev_ratio", "minimum_profit"].includes(
      String(params.sort),
    );
    if (view === "positive_ev")
      params.minimum_ev_ratio = shiftDecimal(filters.threshold ?? "0", -2);
    request<Page<ToolRow | Game>>(
      view === "games" ? "games" : `tools/${view}`,
      { params, signal: controller.signal, snapshot: data.meta.snapshot_id },
    )
      .then((response) => {
        if (!controller.signal.aborted) setPage(response.data);
      })
      .catch((error) => {
        if (!controller.signal.aborted) setPageError(errorText(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setPageLoading(false);
      });
    return () => controller.abort();
  }, [data, view, filters, offset, limit, retry]);
  const quoteMap = useMemo(
    () => new Map(data?.quotes.map((q) => [q.id, q])),
    [data],
  );
  const onPromo = (q: Quote) =>
    router.push(`/promo?quote=${encodeURIComponent(q.id)}`);
  const sort =
    filters.sort ??
    (view === "games"
      ? "starts_at"
      : view === "positive_ev"
        ? "conditional_ev_ratio"
        : "minimum_profit");
  const clear = () => {
    setFilters({});
    setOffset(0);
  };
  return (
    <>
      <a className="skip" href="#main">
        Skip to workspace
      </a>
      <aside className="sidebar" aria-label="Workspace navigation">
        <Link
          className="brand"
          href="/positive_ev"
          aria-label="The Corner — Positive EV"
        >
          <Image
            src="/assets/corner-logo.png"
            alt="Coop's Corner"
            width={170}
            height={170}
            sizes="(max-width: 600px) 52px, 170px"
          />
          <span className="brand-name">
            The Corner
            <span className="brand-sub">Sports market intelligence</span>
          </span>
        </Link>
        <div className="workspace-label">
          <span className="workspace-dot" />
          {showingLive ? "LIVE · PREMIUM" : "PREGAME WORKSPACE"}
        </div>
        <nav ref={navigation} aria-label="Workspace">
          <NavigationLinks current={view} />
        </nav>
        <div className="sidebar-foot">
          <span className={`status-dot ${data ? "connected" : ""}`} />
          <span>
            {light
              ? "Player props workspace"
              : showingLive
                ? "Premium live mode"
                : data
                  ? data.meta.data_mode === "database"
                    ? "Workspace connected"
                    : "Demo data connected"
                  : bootError
                    ? "Workspace temporarily unavailable"
                    : "Connecting to your workspace"}
          </span>
          <small>
            {light
              ? "Scheduled player props"
              : showingLive
                ? "Live main-line snapshots"
                : data?.meta.data_mode === "database"
                  ? "Retained pre-game quotes"
                  : "Fixture environment"}{" "}
            · No live execution
          </small>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <span className="breadcrumb">
            Workspace <span>/</span>
            <strong>{TITLES[view]}</strong>
          </span>
          <div className="top-actions">
            {data?.meta.data_mode === "database" && (
              <span className="fixture-badge">Stored pre-game odds</span>
            )}
            {updating && data && (
              <span className="feed-change" role="status">
                ↻ Updating prices…
              </span>
            )}
            {!showingLive && <FreshOdds />}
            <UserMenu />
          </div>
        </header>
        <main id="main" tabIndex={-1}>
          <div className="page-heading">
            <div>
              <p className="eyebrow">THE MARKET, IN FOCUS</p>
              <h1>{TITLES[view]}</h1>
              <p className="subtitle">{DESCRIPTIONS[view]}</p>
            </div>
            <span className="heading-mark" aria-hidden="true">
              {ICONS[view]}
            </span>
          </div>
          {supportsLive && (
            <LiveSwitch enabled={showingLive} onChange={setLiveMode} />
          )}
          {!showingLive && <FeedGuide view={view} />}
          {!showingLive && bootError && data && (
            <div role="status" className="arb-alert">
              <span>Updates delayed. Showing the last loaded prices.</span>
              <button
                className="button secondary"
                onClick={() => setReload((v) => v + 1)}
              >
                Retry update
              </button>
            </div>
          )}
          {showingLive ? (
            <PremiumLiveFeed
              key={`${view}:${user?.id}`}
              kind={
                view === "positive_ev"
                  ? "ev"
                  : view === "arbitrage"
                    ? "arbitrage"
                    : "middle"
              }
            />
          ) : bootError && !data ? (
            <ErrorCard
              message={bootError}
              retry={() => setReload((v) => v + 1)}
            />
          ) : view === "props" ? (
            <PropsFeed reload={reload + scheduledTick} />
          ) : !data ? (
            <Loading text="Connecting to your local workspace…" />
          ) : view === "promo" ? (
            <PromoFeed data={data} />
          ) : isEv(view) ? (
            view === "arbitrage" ? (
              <ArbFeed data={data} />
            ) : view === "games" ? (
              <ScheduleFeed data={data} />
            ) : view === "middle" ? (
              <MiddleFeed data={data} />
            ) : (
              <EvFeed data={data} />
            )
          ) : (
            <>
              <section className="results-panel">
                <details
                  className="filter-disclosure"
                  open={filterOpen}
                  onToggle={(e) => setFilterOpen(e.currentTarget.open)}
                >
                  <summary>
                    Filters <span>Sport · Market · Book ⌄</span>
                  </summary>
                  <form
                    className="filters"
                    aria-label="Filter results"
                    key={`${view}-${JSON.stringify(filters)}`}
                    onSubmit={(e) => {
                      e.preventDefault();
                      const form = e.currentTarget,
                        values = Object.fromEntries(
                          new FormData(form),
                        ) as Filters;
                      if (
                        values.threshold &&
                        (!decimalInput(values.threshold) ||
                          (values.threshold.split(".")[1]?.length ?? 0) > 10)
                      ) {
                        const input = form.elements.namedItem(
                          "threshold",
                        ) as HTMLInputElement;
                        input.setCustomValidity(
                          "Use a nonnegative percentage with at most 10 decimal places.",
                        );
                        input.reportValidity();
                        return;
                      }
                      setFilters({ ...values, sort });
                      setOffset(0);
                      if (matchMedia("(max-width:600px)").matches)
                        setFilterOpen(false);
                    }}
                  >
                    <Select
                      name="sport_key"
                      label="SPORT"
                      value={filters.sport_key}
                      items={data.caps.sports.map((s) => [s, sport(s)])}
                      all="All sports"
                    />
                    <Select
                      name="market_key"
                      label="MARKET"
                      value={filters.market_key}
                      items={data.caps.market_keys.map((m) => [m, MARKETS[m]])}
                      all="All markets"
                    />
                    {view === "games" ? (
                      <label className="field grow">
                        <span>SEARCH EVENTS</span>
                        <input
                          name="search"
                          type="search"
                          maxLength={100}
                          defaultValue={filters.search}
                          placeholder="Find a game or tournament"
                        />
                      </label>
                    ) : (
                      <>
                        <Select
                          name="sportsbook_id"
                          label="SPORTSBOOK"
                          value={filters.sportsbook_id}
                          items={data.caps.books.map((b) => [b.id, b.name])}
                          all="All books"
                        />
                        <Select
                          name="game_id"
                          label="EVENT"
                          value={filters.game_id}
                          items={data.games.map((g) => [g.id, g.name])}
                          all="All events"
                        />
                      </>
                    )}
                    {view === "positive_ev" && (
                      <label className="field threshold">
                        <span>MIN. EV (%)</span>
                        <input
                          name="threshold"
                          inputMode="decimal"
                          defaultValue={filters.threshold ?? "0"}
                          required
                          maxLength={20}
                          onInput={(e) => e.currentTarget.setCustomValidity("")}
                        />
                      </label>
                    )}
                    <button className="button apply" type="submit">
                      Apply filters
                    </button>
                    <button
                      className="reset-button"
                      type="button"
                      onClick={clear}
                    >
                      Reset
                    </button>
                  </form>
                </details>
                <div className="results-toolbar">
                  <div>
                    <h2>
                      {view === "games" ? "Event directory" : "Market results"}{" "}
                      <span className="count">{page?.total ?? "—"}</span>
                    </h2>
                    <p>
                      {view === "games"
                        ? "Best quoted compares raw prices before commission."
                        : view === "positive_ev"
                          ? "EV is conditional on decisive settlement. No unconditional return is estimated."
                          : view === "middle"
                            ? "A double-win window is not a probability model. Middle EV is not estimated."
                            : "Common refunds may return zero profit. Fixed-price examples only."}
                    </p>
                  </div>
                  {view !== "games" && (
                    <label className="sort-label">
                      {view === "positive_ev" ? "Bankroll" : "Total stake"} $
                      <input
                        className="stake-input"
                        inputMode="decimal"
                        value={view === "positive_ev" ? bankroll : stake}
                        maxLength={12}
                        onChange={(e) =>
                          view === "positive_ev"
                            ? setBankroll(e.target.value)
                            : setStake(e.target.value)
                        }
                      />
                    </label>
                  )}
                  <label className="sort-label">
                    Sort by{" "}
                    <select
                      value={sort}
                      onChange={(e) => {
                        setFilters({ ...filters, sort: e.target.value });
                        setOffset(0);
                      }}
                    >
                      {view === "games" ? (
                        <>
                          <option value="starts_at">Start time</option>
                          <option value="name">Event name</option>
                        </>
                      ) : (
                        <>
                          <option
                            value={
                              view === "positive_ev"
                                ? "conditional_ev_ratio"
                                : "minimum_profit"
                            }
                          >
                            {view === "positive_ev"
                              ? "Conditional EV · highest"
                              : "Minimum payoff · highest"}
                          </option>
                          <option value="capital_required">
                            Capital required · lowest
                          </option>
                        </>
                      )}
                      <option value="id">Stable order</option>
                    </select>
                  </label>
                </div>
                <div aria-live="polite" aria-busy={pageLoading}>
                  {pageError ? (
                    <ErrorCard
                      message={pageError}
                      retry={() => setRetry((v) => v + 1)}
                    />
                  ) : pageLoading ? (
                    <Loading text="Loading market results…" />
                  ) : page?.items.length === 0 ? (
                    <div className="empty-state">
                      <h3>No matching results</h3>
                      <p>Try a different market, book or threshold.</p>
                      <button className="button secondary" onClick={clear}>
                        Clear filters
                      </button>
                    </div>
                  ) : (
                    page &&
                    (view === "games" ? (
                      <div className="game-grid">
                        {(page.items as Game[]).map((g) => (
                          <article className="game-card" key={g.id}>
                            <div className="game-top">
                              <span>{g.competition}</span>
                              <span className="phase-tag">Phase unknown</span>
                            </div>
                            <p className="game-time">{date(g.starts_at)}</p>
                            <h3>{g.name}</h3>
                            <OddsMatrix
                              quotes={data.quotes.filter(
                                (q) =>
                                  q.game_id === g.id &&
                                  (!filters.market_key ||
                                    q.market_key === filters.market_key),
                              )}
                              books={data.caps.books}
                              onPromo={onPromo}
                            />
                            <div className="game-bottom">
                              Exact contract · American odds · Current
                              availability unverified
                            </div>
                          </article>
                        ))}
                      </div>
                    ) : (
                      <Cards
                        rows={page.items as ToolRow[]}
                        games={data.games}
                        quotes={quoteMap}
                        books={data.caps.books}
                        onDetail={setDetail}
                        bankroll={
                          decimalInput(bankroll) && bankroll !== "0"
                            ? bankroll
                            : undefined
                        }
                        stake={
                          decimalInput(stake) && stake !== "0"
                            ? stake
                            : undefined
                        }
                      />
                    ))
                  )}
                </div>
                {page && (
                  <div className="pagination">
                    <span>
                      {page.total
                        ? `${page.offset + 1}–${page.offset + page.items.length}`
                        : "0"}{" "}
                      of {page.total} results
                    </span>
                    <div>
                      <label>
                        Rows{" "}
                        <select
                          value={limit}
                          onChange={(e) => {
                            setLimit(Number(e.target.value));
                            setOffset(0);
                          }}
                        >
                          {[10, 25, 50].map((n) => (
                            <option key={n}>{n}</option>
                          ))}
                        </select>
                      </label>
                      <button
                        className="page-button"
                        disabled={offset === 0}
                        aria-label="Previous page"
                        onClick={() => setOffset(Math.max(0, offset - limit))}
                      >
                        ←
                      </button>
                      <button
                        className="page-button"
                        disabled={page.next_offset === null}
                        aria-label="Next page"
                        onClick={() => setOffset(page.next_offset ?? offset)}
                      >
                        →
                      </button>
                    </div>
                  </div>
                )}
              </section>
              <p className="fineprint">
                {data?.meta.data_mode === "database"
                  ? "Stored provider prices"
                  : "Synthetic prices"}{" "}
                · American odds · USD display ($1 per calculation unit).
                Fixed-price examples; current availability is unverified.
              </p>
            </>
          )}
          <footer className="page-footer">
            <span>
              {showingLive
                ? "Live snapshots · prices and availability can change before acceptance"
                : data
                  ? `${data.meta.data_mode === "database" ? "Newest stored quote" : "Fixture captured"} ${date(data.meta.captured_at)} · Not a live refresh`
                  : "No snapshot loaded"}
            </span>
            <span>Exact inputs. Transparent calculations.</span>
          </footer>
        </main>
      </div>
      {!showingLive && detail && data && (
        <Details
          row={detail}
          quotes={quoteMap}
          books={data.caps.books}
          live={data.meta.data_mode === "database"}
          onClose={() => setDetail(null)}
        />
      )}
    </>
  );
}
function Select({
  name,
  label,
  value,
  items,
  all,
}: {
  name: string;
  label: string;
  value?: string;
  items: [string, string][];
  all: string;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <select name={name} defaultValue={value ?? ""}>
        <option value="">{all}</option>
        {items.map(([key, label]) => (
          <option value={key} key={key}>
            {label}
          </option>
        ))}
      </select>
    </label>
  );
}

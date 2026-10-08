"use client";
import Link from "next/link";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  MARKETS,
  TITLES,
  date,
  sport,
  decimalInput,
  shiftDecimal,
} from "../../frontend/format.mjs";
import { allPages, request } from "../lib/api";
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
import { VIEWS } from "../lib/contracts";
import { Cards, Details, OddsMatrix } from "./market-views";
import PromoFeed from "./promo-feed";
import EvFeed from "./ev-feed";
import ArbFeed from "./arb-feed";
import MiddleFeed from "./middle-feed";
import OddsScreen from "./odds-screen";
import PropsFeed from "./props-feed";
import FreshOdds from "./fresh-odds";

const DESCRIPTIONS: Record<View, string> = {
  positive_ev: "Compare offered odds with a complete reference-book estimate.",
  arbitrage:
    "Explore complementary positions and their decisive-settlement payoffs.",
  middle:
    "Find cross-line windows. See the upside and the cost of missing the middle.",
  props:
    "Player prop bets priced against the same sharp books as the Positive EV feed.",
  games:
    "One event. Every featured market. The exact quotes behind each calculation.",
  promo:
    "Explore bonus and refund economics without confusing tokens with cash.",
};
const ICONS: Record<View, string> = {
  positive_ev: "↗",
  arbitrage: "⇄",
  middle: "⋈",
  props: "♟",
  games: "▦",
  promo: "◇",
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
const errorText = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "An unexpected request error occurred.";
export function Loading({ text }: { text: string }) {
  return (
    <div className="loading" role="status">
      <span className="spinner" />
      {text}
    </div>
  );
}
export function ErrorCard({
  message,
  retry,
}: {
  message: string;
  retry: () => void;
}) {
  return (
    <div className="error-card" role="alert">
      <h3>Unable to complete this request</h3>
      <p>{message}</p>
      <button className="button" onClick={retry}>
        Try again
      </button>
    </div>
  );
}
export default function Workspace({ view }: { view: View }) {
  const router = useRouter();
  const [data, setData] = useState<Data | null>(null),
    [bootError, setBootError] = useState(""),
    [reload, setReload] = useState(0);
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
  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setDetail(null);
    setBootError("");
    (async () => {
      try {
        await reloadToolsOnce();
        if (controller.signal.aborted) return;
        const caps = await request<Capabilities>("capabilities", {
          signal: controller.signal,
        });
        const games = await allPages<Game>(
          "games",
          caps.meta.snapshot_id,
          controller.signal,
        );
        const boards = await Promise.all(
          games.map((g) =>
            allPages<Quote>(
              `games/${encodeURIComponent(g.id)}/odds`,
              caps.meta.snapshot_id,
              controller.signal,
            ),
          ),
        );
        if (!controller.signal.aborted)
          setData({
            caps: caps.data,
            games,
            quotes: boards.flat(),
            meta: caps.meta,
          });
      } catch (error) {
        if (!controller.signal.aborted) setBootError(errorText(error));
      }
    })();
    return () => controller.abort();
  }, [reload]);
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
  const quoteMap = new Map(data?.quotes.map((q) => [q.id, q]));
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
          LOCAL WORKSPACE <span className="version">01</span>
        </div>
        <nav>
          <p className="nav-label">FIND AN EDGE</p>
          {VIEWS.map((v, i) => (
            <span key={v}>
              {i === 4 && (
                <p className="nav-label second">EXPLORE &amp; CALCULATE</p>
              )}
              <Link
                href={`/${v}`}
                className={view === v ? "active" : ""}
                aria-current={view === v ? "page" : undefined}
              >
                <span className="nav-icon">{ICONS[v]}</span>
                {TITLES[v]}
              </Link>
            </span>
          ))}
          <Link href="/tracker">
            <span className="nav-icon">◎</span>Tracker &amp; bankroll
          </Link>
        </nav>
        <div className="sidebar-foot">
          <span className={`status-dot ${data ? "connected" : ""}`} />
          <span>
            {data
              ? data.meta.data_mode === "database"
                ? "Local tools API connected"
                : "Local fixture API connected"
              : bootError
                ? "Local API unavailable"
                : "Connecting to local API"}
          </span>
          <small>
            {data?.meta.data_mode === "database"
              ? "Retained pre-game quotes"
              : "Fixture environment"}{" "}
            · No live execution
          </small>
          <span>Next.js · TypeScript</span>
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
              <span className="fixture-badge">◇ Stored pre-game odds</span>
            )}
            <FreshOdds onRefreshed={() => setReload((v) => v + 1)} />
          </div>
        </header>
        <main id="main" tabIndex={-1}>
          <section className="corner-banner" aria-label="The Corner community">
            <Image
              src="/assets/corner-banner.png"
              alt="Coop's Corner"
              width={1500}
              height={500}
              sizes="(max-width: 600px) 360px, 330px"
              fetchPriority="high"
            />
            <div className="corner-banner-copy">
              <p>THE COMMUNITY. THE INTELLIGENCE. THE EDGE.</p>
              <h2>Your edge. Your Corner.</h2>
              <span>Compare the market. Understand the payoff.</span>
            </div>
          </section>
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
          {bootError ? (
            <ErrorCard
              message={bootError}
              retry={() => setReload((v) => v + 1)}
            />
          ) : !data ? (
            <Loading text="Connecting to your local workspace…" />
          ) : view === "promo" ? (
            <PromoFeed data={data} />
          ) : isEv(view) ? (
            view === "arbitrage" ? (
              <ArbFeed data={data} />
            ) : view === "games" ? (
              <OddsScreen data={data} />
            ) : view === "middle" ? (
              <MiddleFeed data={data} />
            ) : view === "props" ? (
              <PropsFeed reload={reload} />
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
              {data
                ? `${data.meta.data_mode === "database" ? "Newest stored quote" : "Fixture captured"} ${date(data.meta.captured_at)} · Not a live refresh`
                : "No snapshot loaded"}
            </span>
            <span>Exact inputs. Transparent calculations.</span>
          </footer>
        </main>
      </div>
      {detail && data && (
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

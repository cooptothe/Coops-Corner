"use client";
import { Icon } from "./icon";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { american, date, fixed, mulDecimal } from "../../frontend/format.mjs";
import { bookDisplayName, feedBooks } from "../lib/bookmakers";
import { userStorage } from "../lib/user-storage";
import {
  parlayKind,
  acceptedAmericanOdds,
  legKey,
  parlayHandoff,
  parlayDestination,
  supportsCombinedSlip,
  readDraft,
  selectionProblem,
  type ParlayDraft,
  type ParlayLeg,
} from "../lib/parlay";
import { addBets } from "../lib/tracker-api";
import { notifyLogged } from "../lib/slip";
import { BetLinkButton } from "./bet-link";
import { useBettingPrefs } from "./betting-prefs";

const STORAGE = "corner.parlay-draft.v1";
const emptyDraft = (): ParlayDraft => ({
  id: crypto.randomUUID(),
  book: "",
  stake: "",
  active: false,
  legs: [],
});
type Context = {
  draft: ParlayDraft;
  selected: (key: string) => boolean;
  toggle: (leg: ParlayLeg) => void;
  start: () => void;
  pause: () => void;
  register: (source: string, legs: ParlayLeg[]) => void;
};
const ParlayContext = createContext<Context | null>(null);
export function useParlay() {
  return useContext(ParlayContext);
}

export function ParlayProvider({ children }: { children: ReactNode }) {
  const [draft, setDraft] = useState<ParlayDraft>({
    id: "",
    book: "",
    stake: "",
    active: false,
    legs: [],
  });
  const [ready, setReady] = useState(false);
  const [picker, setPicker] = useState(false);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [acceptedOdds, setAcceptedOdds] = useState("");
  const [placedAt, setPlacedAt] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [available, setAvailable] = useState<Record<string, ParlayLeg[]>>({});
  const draftRef = useRef(draft);
  const busyRef = useRef(busy);
  busyRef.current = busy;
  const pickerRef = useRef<HTMLElement>(null);
  draftRef.current = draft;
  const pathname = usePathname();
  const { state } = useBettingPrefs();
  useEffect(() => {
    if (!picker) return;
    const previous = document.activeElement as HTMLElement | null;
    const root = pickerRef.current;
    const focusable = () => [
      ...(root?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), a[href], input, select, [tabindex="0"]',
      ) ?? []),
    ];
    focusable()[0]?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setPicker(false);
      }
      if (event.key !== "Tab") return;
      const nodes = focusable();
      if (event.shiftKey && document.activeElement === nodes[0]) {
        event.preventDefault();
        nodes.at(-1)?.focus();
      }
      if (!event.shiftKey && document.activeElement === nodes.at(-1)) {
        event.preventDefault();
        nodes[0]?.focus();
      }
    };
    document.addEventListener("keydown", keydown);
    return () => {
      document.removeEventListener("keydown", keydown);
      previous?.focus();
    };
  }, [picker]);
  const feedPage =
    pathname === "/positive_ev" ||
    pathname === "/props" ||
    pathname === "/lab" ||
    pathname === "/";
  useEffect(() => {
    document.body.classList.toggle(
      "parlay-panel-open",
      !!(ready && feedPage && open && draft.book),
    );
    return () => document.body.classList.remove("parlay-panel-open");
  }, [ready, feedPage, open, draft.book]);
  useEffect(() => {
    if (!open || picker) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [open, picker]);
  useEffect(() => {
    try {
      setDraft(
        readDraft(JSON.parse(userStorage.getItem(STORAGE) ?? "null")) ??
          emptyDraft(),
      );
    } catch {
      setDraft(emptyDraft());
    }
    setReady(true);
  }, []);
  useEffect(() => {
    if (ready) userStorage.setItem(STORAGE, JSON.stringify(draft));
  }, [draft, ready]);
  const register = useCallback((source: string, legs: ParlayLeg[]) => {
    setAvailable((current) => ({ ...current, [source]: legs }));
  }, []);
  const toggle = useCallback((leg: ParlayLeg) => {
    if (busyRef.current) return;
    const current = draftRef.current;
    if (current.legs.some((l) => l.key === leg.key)) {
      setDraft({
        ...current,
        legs: current.legs.filter((l) => l.key !== leg.key),
      });
    } else {
      const problem = selectionProblem(current, leg);
      if (problem) {
        setError(problem);
        setOpen(true);
        return;
      }
      setDraft({ ...current, legs: [...current.legs, leg] });
    }
    setError("");
    setNotice("");

    setConfirmed(false);
    setOpen((wasOpen) =>
      window.matchMedia("(max-width:700px)").matches ? wasOpen : true,
    );
  }, []);
  const context = useMemo<Context>(
    () => ({
      draft,
      toggle,
      register,
      selected: (key) => draft.legs.some((leg) => leg.key === key),
      start: () => {
        if (draft.book) {
          setDraft({ ...draft, active: true });
          setOpen(true);
        } else setPicker(true);
      },
      pause: () => {
        setDraft({ ...draft, active: false });
        setOpen(false);
      },
    }),
    [draft, toggle, register],
  );
  const estimated = (() => {
    try {
      return acceptedOdds.trim() ? acceptedAmericanOdds(acceptedOdds) : null;
    } catch {
      return null;
    }
  })();
  const handoff = parlayHandoff(draft.legs, state);
  const destination = parlayDestination(draft.legs, state);
  const run = async (work: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await work();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "The parlay could not be updated.",
      );
    } finally {
      setBusy(false);
    }
  };
  const log = () =>
    run(async () => {
      if (!confirmed)
        throw new Error("Confirm that you placed this wager first.");
      if (
        !/^\d{1,9}(\.\d{1,2})?$/.test(draft.stake) ||
        Number(draft.stake) <= 0
      )
        throw new Error("Enter the accepted stake in dollars.");
      const acceptedDecimal = acceptedAmericanOdds(acceptedOdds);
      if (!placedAt) throw new Error("Enter the placement time.");
      await addBets([
        {
          client_key: `parlay:${draft.id}`,
          strategy: "parlay",
          book: draft.book,
          matchup: `${draft.legs.length}-leg parlay`,
          selection: parlayKind(draft.legs),
          market: "parlay",
          odds: acceptedDecimal,
          stake: draft.stake,
          placed_at: new Date(placedAt).toISOString(),
          starts_at: [...draft.legs].sort((a, b) =>
            a.startsAt.localeCompare(b.startsAt),
          )[0].startsAt,
          sport_key: "",
          ref: {},
          legs: draft.legs.map((leg) => ({
            key: leg.key,
            event_id: leg.eventId,
            source: leg.source,
            book: leg.book,
            matchup: leg.matchup,
            starts_at: leg.startsAt,
            sport_key: leg.sportKey,
            market: leg.market,
            selection: leg.selection,
            odds: leg.odds,
            ref: leg.ref,
          })),
        },
      ]);
      notifyLogged();
      setAcceptedOdds("");
      setPlacedAt("");
      setDraft(emptyDraft());

      setConfirmed(false);
      setOpen(false);
      setNotice("Parlay recorded in your tracker.");
    });
  const books = feedBooks(
    Object.values(available)
      .flat()
      .map((leg) => ({ id: leg.book, name: bookDisplayName(leg.book) })),
    true,
  );
  return (
    <ParlayContext.Provider value={context}>
      {children}
      {notice === "Parlay recorded in your tracker." && (
        <div className="parlay-toast" role="status">
          Parlay recorded. <Link href="/tracker">View tracker</Link>
          <button
            aria-label="Dismiss confirmation"
            onClick={() => setNotice("")}
          >
            <Icon name="close" />
          </button>
        </div>
      )}
      {ready && feedPage && (draft.active || draft.legs.length > 0) && (
        <button
          className="parlay-mobile-toggle button"
          onClick={() => setOpen(!open)}
        >
          View parlay · {draft.legs.length} legs
        </button>
      )}
      {picker && (
        <div
          className="parlay-backdrop"
          role="presentation"
          onClick={() => setPicker(false)}
        >
          <section
            ref={pickerRef}
            className="parlay-book-picker"
            role="dialog"
            aria-modal="true"
            aria-labelledby="parlay-picker-title"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 id="parlay-picker-title">Choose your sportsbook</h2>
            <p>
              Build a parlay using main lines, props, or both. Same-game
              combinations use the sportsbook’s combined price.
            </p>
            <button
              className="parlay-close"
              aria-label="Close sportsbook picker"
              onClick={() => setPicker(false)}
            >
              <Icon name="close" />
            </button>
            <div className="parlay-books">
              {books.map((book) => (
                <button
                  className="button secondary"
                  disabled={busy}
                  key={book.id}
                  onClick={() => {
                    if (
                      draft.legs.length &&
                      book.id !== draft.book &&
                      !window.confirm(
                        "Changing books clears the current draft. Continue?",
                      )
                    )
                      return;
                    setDraft(
                      book.id === draft.book
                        ? { ...draft, active: true }
                        : { ...emptyDraft(), book: book.id, active: true },
                    );
                    setPicker(false);
                    setOpen(true);

                    setNotice("");
                    setError("");
                  }}
                >
                  {book.name}
                  <small>
                    {
                      Object.values(available)
                        .flat()
                        .filter((leg) => leg.book === book.id).length
                    }{" "}
                    available ·{" "}
                    {supportsCombinedSlip(book.id)
                      ? "Combined-slip support"
                      : "Book & leg links"}
                  </small>
                </button>
              ))}
            </div>
          </section>
        </div>
      )}
      {ready && feedPage && open && draft.book && (
        <aside className="parlay-panel" aria-label="Parlay builder">
          <button
            className="parlay-close"
            aria-label="Close parlay panel"
            onClick={() => setOpen(false)}
          >
            <Icon name="close" />
          </button>
          <h2>{bookDisplayName(draft.book)} parlay</h2>
          {!!draft.legs.length && (
            <p className="trk-muted">{parlayKind(draft.legs)}</p>
          )}
          <div className="parlay-actions">
            <button
              className="button secondary"
              disabled={busy}
              onClick={() => setPicker(true)}
            >
              Change book
            </button>
            <button
              className="button secondary"
              disabled={busy}
              onClick={() => {
                if (
                  draft.legs.length &&
                  !window.confirm("Clear this parlay draft?")
                )
                  return;
                setDraft({ ...emptyDraft(), book: draft.book, active: true });

                setNotice("");
                setError("");
              }}
            >
              Clear slip
            </button>
          </div>
          <nav className="parlay-actions">
            <Link href="/positive_ev">Main-line +EV</Link>
            <Link href="/props">Player props</Link>
          </nav>
          {!draft.legs.length && (
            <p>
              Click bets in the feed or The Lab to add your first leg. Combine
              selections from the same game or different games.
            </p>
          )}
          <ol className="parlay-legs">
            {draft.legs.map((leg) => (
              <li key={leg.key}>
                <strong>{leg.selection}</strong>
                <span>
                  {leg.matchup} · {leg.market}
                </span>
                <small>{date(leg.startsAt)}</small>
                <span>
                  {american(leg.odds)} ·{" "}
                  {leg.source === "prop" ? "Player prop" : "Main line"}
                </span>
                <button
                  className="parlay-remove"
                  aria-label={`Remove ${leg.selection}`}
                  onClick={() => toggle(leg)}
                >
                  <Icon name="close" />
                </button>
                <BetLinkButton
                  links={leg.links}
                  bookLabel={bookDisplayName(leg.book)}
                  startsAt={leg.startsAt}
                  compact
                />
              </li>
            ))}
          </ol>
          <label className="field">
            <span>STAKE ($)</span>
            <input
              inputMode="decimal"
              value={draft.stake}
              disabled={busy}
              onChange={(e) => setDraft({ ...draft, stake: e.target.value })}
            />
          </label>
          {draft.legs.length >= 2 && estimated !== null && (
            <p className="parlay-estimate">
              Entered combined odds <strong>{american(estimated)}</strong>
              <br />
              Potential gross return{" "}
              <strong>
                $
                {/^[\d]+(\.\d{1,2})?$/.test(draft.stake) &&
                Number(draft.stake) > 0
                  ? fixed(mulDecimal(draft.stake, estimated), 2)
                  : "0.00"}
              </strong>
            </p>
          )}
          {draft.legs.length >= 2 && estimated === null && (
            <p className="parlay-estimate">
              Combined odds and return: <strong>Get quote at sportsbook</strong>
              <br />
              Enter your sportsbook's combined American odds below. Individual
              leg prices are reference information only; no live quote review is
              required to record your wager.
            </p>
          )}
          {busy && <p role="status">Saving…</p>}
          {notice && <p role="status">{notice}</p>}
          {error && (
            <p role="alert" className="parlay-error">
              {error}
            </p>
          )}
          {destination.url ? (
            <a
              className="button"
              href={destination.url}
              target="_blank"
              rel="noopener noreferrer"
              referrerPolicy="no-referrer"
            >
              {destination.combined ? "Open slip on" : "Open"}{" "}
              {bookDisplayName(draft.book)} <Icon name="external" />
            </a>
          ) : (
            <button className="button" disabled>
              Sportsbook link unavailable
            </button>
          )}
          {draft.legs.length >= 2 && handoff.reason && (
            <small>{handoff.reason}</small>
          )}
          <button
            className="button secondary"
            disabled={!draft.legs.length}
            onClick={() =>
              run(async () => {
                await navigator.clipboard.writeText(
                  [
                    bookDisplayName(draft.book),
                    parlayKind(draft.legs),
                    ...draft.legs.map(
                      (leg, i) =>
                        `${i + 1}. ${leg.matchup} — ${leg.selection} (${american(leg.odds)})`,
                    ),
                    ...(estimated === null
                      ? [
                          "Combined price: request the sportsbook’s same-game parlay quote.",
                        ]
                      : []),
                  ].join("\n"),
                );
                setNotice("Slip copied.");
              })
            }
          >
            Copy slip
          </button>
          <details className="parlay-record" open>
            <summary>Already placed? Track this parlay</summary>
            <label className="field">
              <span>ACCEPTED AMERICAN ODDS</span>
              <input
                inputMode="text"
                value={acceptedOdds}
                placeholder="e.g. +325 or -150"
                maxLength={10}
                onChange={(e) => setAcceptedOdds(e.target.value)}
              />
            </label>
            <label className="field">
              <span>PLACEMENT TIME</span>
              <input
                type="datetime-local"
                value={placedAt}
                onChange={(e) => setPlacedAt(e.target.value)}
              />
            </label>
            <label>
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
              />{" "}
              I placed this wager at the sportsbook.
            </label>
            <button
              className="button"
              disabled={busy || !confirmed || draft.legs.length < 2}
              onClick={log}
            >
              Record placed parlay
            </button>
          </details>
          <small>
            The sportsbook confirms final odds and whether the legs can be
            combined. Opening a slip does not place or record a wager.
          </small>
        </aside>
      )}
    </ParlayContext.Provider>
  );
}

export function ParlayToolbar() {
  const parlay = useParlay();
  if (!parlay) return null;
  return (
    <div className="parlay-toolbar">
      <button
        className={`button ${parlay.draft.active ? "" : "secondary"}`}
        aria-pressed={parlay.draft.active}
        onClick={parlay.draft.active ? parlay.pause : parlay.start}
      >
        {parlay.draft.active ? "Exit parlay mode" : "Parlay mode"}
      </button>
      {parlay.draft.active && (
        <span>
          {bookDisplayName(parlay.draft.book)} · {parlay.draft.legs.length} legs
          · click a bet to add it
        </span>
      )}
    </div>
  );
}

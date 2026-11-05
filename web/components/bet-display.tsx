"use client";
import { useEffect, useState, type ComponentProps } from "react";
import { MAIN_BOOKS } from "../lib/bookmakers";
import { subscribeStorageOwner, userStorage } from "../lib/user-storage";

export interface BetScreen {
  label: string;
  availLeft: number;
  availTop: number;
  availWidth: number;
  availHeight: number;
}
interface ScreenDetails extends EventTarget {
  screens: BetScreen[];
}
type DisplayWindow = Window & {
  getScreenDetails?: () => Promise<ScreenDetails>;
};
export interface DisplayPreferences {
  defaultScreen: string;
  books: Record<string, string>;
}
const KEY = "corner-bet-displays-v1";
const listeners = new Set<() => void>();
let details: ScreenDetails | undefined;
let loading: Promise<ScreenDetails> | undefined;
let priming: Promise<void> | undefined;
export const screenKey = (screen: BetScreen) =>
  JSON.stringify([screen.label, screen.availLeft, screen.availTop]);
export const screenFeatures = (screen: BetScreen) =>
  `popup=yes,left=${screen.availLeft},top=${screen.availTop},width=${screen.availWidth},height=${screen.availHeight},noopener,noreferrer`;
export function parseDisplayPreferences(
  raw: string | null,
): DisplayPreferences {
  const empty = { defaultScreen: "", books: {} };
  try {
    const data = JSON.parse(raw || "null");
    if (!data || typeof data !== "object") return empty;
    const books: Record<string, string> = {};
    for (const book of MAIN_BOOKS)
      if (typeof data.books?.[book.id] === "string")
        books[book.id] = data.books[book.id];
    return {
      defaultScreen:
        typeof data.defaultScreen === "string" ? data.defaultScreen : "",
      books,
    };
  } catch {
    return empty;
  }
}
function preference() {
  try {
    return parseDisplayPreferences(userStorage.getItem(KEY));
  } catch {
    return parseDisplayPreferences(null);
  }
}
export function displayForBook(prefs: DisplayPreferences, book?: string) {
  const normalize = (value: string) =>
    value.toLowerCase().replace(/[^a-z0-9]/g, "");
  const match = MAIN_BOOKS.find(
    (b) =>
      normalize(b.id) === normalize(book || "") ||
      normalize(b.name) === normalize(book || ""),
  );
  return match && Object.hasOwn(prefs.books, match.id)
    ? prefs.books[match.id]
    : prefs.defaultScreen;
}
function notify() {
  listeners.forEach((fn) => fn());
}
async function loadDisplays() {
  if (loading) return loading;
  const api = window as DisplayWindow;
  if (!api.getScreenDetails) throw new Error("unsupported");
  loading = api
    .getScreenDetails()
    .then((next) => {
      details?.removeEventListener("screenschange", notify);
      details = next;
      details.addEventListener("screenschange", notify);
      notify();
      return next;
    })
    .finally(() => {
      loading = undefined;
    });
  return loading;
}
function primeDisplays() {
  if (priming) return priming;
  priming = (async () => {
    if (!(window as DisplayWindow).getScreenDetails || !navigator.permissions)
      return;
    try {
      const permission = await navigator.permissions.query({
        name: "window-management" as PermissionName,
      });
      permission.addEventListener("change", () => {
        if (permission.state !== "granted") {
          details?.removeEventListener("screenschange", notify);
          details = undefined;
          notify();
        }
      });
      if (permission.state === "granted") await loadDisplays();
    } catch {
      /* No prompts on load; unsupported browsers keep their usual links. */
    }
  })();
  return priming;
}
export function openDisplayWindow(
  href: string,
  screen: BetScreen,
  api: Pick<Window, "open">,
): boolean {
  let popup: Window | null = null;
  try {
    // Opening synchronously preserves the click gesture. Detach the opener
    // before external navigation; a blocked window leaves the real anchor intact.
    popup = api.open(
      "about:blank",
      "_blank",
      screenFeatures(screen).replace(",noopener,noreferrer", ""),
    );
    if (!popup) return false;
    popup.opener = null;
    const meta = popup.document.createElement("meta");
    meta.name = "referrer";
    meta.content = "no-referrer";
    popup.document.head.appendChild(meta);
    popup.location.replace(href);
    return true;
  } catch {
    try {
      popup?.close();
    } catch {}
    return false;
  }
}
export function SportsbookLink({
  onClick,
  book,
  ...props
}: ComponentProps<"a"> & { book?: string }) {
  useEffect(() => {
    void primeDisplays();
  }, []);
  return (
    <a
      {...props}
      onClick={(event) => {
        onClick?.(event);
        if (
          event.defaultPrevented ||
          event.button !== 0 ||
          event.metaKey ||
          event.ctrlKey ||
          event.shiftKey ||
          event.altKey
        )
          return;
        const chosen = displayForBook(preference(), book);
        const screen = details?.screens.find((s) => screenKey(s) === chosen);
        if (
          screen &&
          props.href &&
          openDisplayWindow(props.href, screen, window)
        )
          event.preventDefault();
      }}
    />
  );
}
export function BetDisplaySettings() {
  const [screens, setScreens] = useState<BetScreen[]>([]);
  const [prefs, setPrefs] = useState<DisplayPreferences>({
    defaultScreen: "",
    books: {},
  });
  const [supported, setSupported] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => {
    setSupported(
      typeof (window as DisplayWindow).getScreenDetails === "function",
    );
    const update = () => {
      setScreens([...(details?.screens ?? [])]);
      setPrefs(preference());
    };
    update();
    listeners.add(update);
    const unsubscribe = subscribeStorageOwner(update);
    window.addEventListener("storage", update);
    void primeDisplays().then(update);
    return () => {
      listeners.delete(update);
      unsubscribe();
      window.removeEventListener("storage", update);
    };
  }, []);
  function save(next: DisplayPreferences) {
    try {
      userStorage.setItem(KEY, JSON.stringify(next));
      if (userStorage.getItem(KEY) !== JSON.stringify(next))
        throw new Error("not saved");
      setPrefs(next);
      notify();
      setMessage("Display setup saved on this computer.");
    } catch {
      setMessage("Your browser could not save this setup.");
    }
  }
  function options(value: string, inherit = false) {
    return (
      <>
        {inherit && <option value="inherit">Use default display</option>}
        <option value="">Default browser tab</option>
        {value && !screens.some((s) => screenKey(s) === value) && (
          <option value={value}>Saved display (not connected)</option>
        )}
        {screens.map((screen, i) => (
          <option key={screenKey(screen)} value={screenKey(screen)}>
            {screen.label || `Display ${i + 1}`} ({screen.availWidth} ×{" "}
            {screen.availHeight})
          </option>
        ))}
      </>
    );
  }
  return (
    <section
      className="trk-card account-card"
      aria-labelledby="bet-display-title"
    >
      <h3 id="bet-display-title">One-click bet displays</h3>
      <p className="trk-muted">
        Choose a default monitor, then assign individual sportsbooks.
      </p>
      <div className="bet-display-actions">
        {supported ? (
          <button
            type="button"
            className="button secondary"
            onClick={async () => {
              try {
                const next = await loadDisplays();
                setScreens([...next.screens]);
                setMessage(
                  next.screens.length < 2
                    ? "One display detected. Connect another monitor and refresh."
                    : "Displays connected. Choose your setup below.",
                );
              } catch {
                setMessage(
                  "Display access is unavailable. Allow display access in your browser settings, then try again.",
                );
              }
            }}
          >
            {screens.length ? "Refresh displays" : "Connect displays"}
          </button>
        ) : (
          <p className="trk-muted">
            Display selection requires a supported desktop browser, such as
            Chrome or Edge.
          </p>
        )}
        <SportsbookLink
          className="button secondary"
          href="/account"
          target="_blank"
          rel="noopener noreferrer"
          referrerPolicy="no-referrer"
        >
          Test default display
        </SportsbookLink>
      </div>
      <label className="field">
        <span>Default display</span>
        <select
          value={prefs.defaultScreen}
          onChange={(e) => save({ ...prefs, defaultScreen: e.target.value })}
        >
          {options(prefs.defaultScreen)}
        </select>
      </label>
      <details>
        <summary>Sportsbook overrides</summary>
        <div className="bet-display-books">
          {MAIN_BOOKS.map((book) => (
            <label className="field" key={book.id}>
              <span>{book.name}</span>
              <select
                aria-label={`${book.name} display`}
                value={prefs.books[book.id] ?? "inherit"}
                onChange={(e) => {
                  const books = { ...prefs.books };
                  if (e.target.value === "inherit") delete books[book.id];
                  else books[book.id] = e.target.value;
                  save({ ...prefs, books });
                }}
              >
                {options(prefs.books[book.id] || "", true)}
              </select>
            </label>
          ))}
        </div>
      </details>
      <p className="trk-muted">
        Saved for your account in this browser. Allow popups for this site.
        Disconnected displays use the default browser tab.{" "}
        <a href="/help#links">Help &amp; guide</a>
      </p>
      {message && <p role="status">{message}</p>}
    </section>
  );
}

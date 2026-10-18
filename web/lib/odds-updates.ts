import { invalidateSharedPages } from "./api";

export const ODDS_UPDATED = "corner:odds-updated";
export const ODDS_STORAGE_KEY = "corner.odds-updated";
type UpdateTarget = EventTarget & {
  localStorage?: Pick<Storage, "setItem">;
};
const browser = (): UpdateTarget | undefined =>
  typeof window === "undefined" ? undefined : window;

// Contains only an invalidation signal, never odds, account data or credentials.
export function announceOddsUpdated(target = browser()): void {
  invalidateSharedPages();
  if (!target) return;
  target.dispatchEvent(new Event(ODDS_UPDATED));
  try {
    target.localStorage?.setItem(ODDS_STORAGE_KEY, crypto.randomUUID());
  } catch {
    // Private browsing/storage restrictions must not break the current tab.
  }
}

export function subscribeOddsUpdated(
  listener: () => void,
  target = browser(),
): () => void {
  if (!target) return () => undefined;
  const updated = () => {
    invalidateSharedPages();
    listener();
  };
  const stored = (event: Event) => {
    if ((event as StorageEvent).key === ODDS_STORAGE_KEY) updated();
  };
  target.addEventListener(ODDS_UPDATED, updated);
  target.addEventListener("storage", stored);
  return () => {
    target.removeEventListener(ODDS_UPDATED, updated);
    target.removeEventListener("storage", stored);
  };
}

import { notifyUnauthorized } from "./auth-api";
// Client cache for team logos and player headshots.
//
// Components ask for a name; requests for the same league are batched into one call to the local
// media service, results are kept for the life of the page, and the browser caches the images
// themselves. A failed lookup is retried a few times and then simply shows initials.
export type MediaKind = "team" | "player";

const cache = new Map<string, string | null>();
const queued = new Map<string, Set<string>>();
const pending = new Set<string>();
const jobs: (() => Promise<void>)[] = [];
let active = 0;
const CONCURRENCY = 3;
function pump() {
  while (active < CONCURRENCY && jobs.length) {
    const job = jobs.shift()!;
    active++;
    void job().finally(() => {
      active--;
      pump();
    });
  }
}
const attempts = new Map<string, number>();
const listeners = new Map<string, Set<() => void>>();
let flushTimer: ReturnType<typeof setTimeout> | undefined;

const BATCH = 40;
const FLUSH_MS = 40;
const MAX_ATTEMPTS = 3;
const RETRY_MS = 15000;

const keyOf = (kind: MediaKind, sport: string, name: string) =>
  `${kind}|${sport}|${name}`;
export const subscribeMedia = (
  kind: MediaKind,
  sport: string,
  name: string,
  listener: () => void,
) => {
  const key = keyOf(kind, sport, name);
  let set = listeners.get(key);
  if (!set) listeners.set(key, (set = new Set()));
  set.add(listener);
  return () => {
    set.delete(listener);
    if (!set.size) listeners.delete(key);
  };
};

// undefined = not resolved yet, null = resolved with no image.
export const readMedia = (kind: MediaKind, sport: string, name: string) =>
  cache.get(keyOf(kind, sport, name));

export const isIndividualSport = (sportKey: string) =>
  sportKey.startsWith("tennis_") || sportKey.startsWith("mma_");

function settle(
  kind: MediaKind,
  sport: string,
  names: string[],
  results: Record<string, string | null>,
  retry: Set<string>,
) {
  const again: string[] = [];
  const completed: string[] = [];
  for (const name of names) {
    const key = keyOf(kind, sport, name);
    if (retry.has(name) && (attempts.get(key) ?? 0) < MAX_ATTEMPTS) {
      attempts.set(key, (attempts.get(key) ?? 0) + 1);
      again.push(name);
    } else {
      cache.set(key, results[name] ?? null);
      completed.push(key);
      pending.delete(key);
    }
  }
  if (again.length)
    setTimeout(() => {
      for (const name of again) {
        pending.delete(keyOf(kind, sport, name));
        enqueue(kind, sport, name);
      }
      schedule();
    }, RETRY_MS);
  for (const key of completed)
    listeners.get(key)?.forEach((notify) => notify());
}

async function send(kind: MediaKind, sport: string, names: string[]) {
  const params = new URLSearchParams({ kind, sport });
  for (const name of names) params.append("n", name);
  try {
    const response = await fetch(`/api/refresh/v1/media/resolve?${params}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(60000),
    });
    if (response.status === 401) notifyUnauthorized();
    if (!response.ok) throw new Error("media unavailable");
    const body = (await response.json()) as {
      results: Record<string, string | null>;
      retry: string[];
    };
    settle(kind, sport, names, body.results, new Set(body.retry));
  } catch {
    settle(kind, sport, names, {}, new Set(names));
  }
}

function flush() {
  flushTimer = undefined;
  for (const [group, names] of queued) {
    queued.delete(group);
    const [kind, sport] = group.split("|") as [MediaKind, string];
    const list = [...names];
    for (let i = 0; i < list.length; i += BATCH) {
      const batch = list.slice(i, i + BATCH);
      jobs.push(() => send(kind, sport, batch));
    }
  }
  pump();
}

const schedule = () => {
  flushTimer ??= setTimeout(flush, FLUSH_MS);
};

function enqueue(kind: MediaKind, sport: string, name: string) {
  const key = keyOf(kind, sport, name);
  if (cache.has(key) || pending.has(key)) return;
  pending.add(key);
  const group = `${kind}|${sport}`;
  let names = queued.get(group);
  if (!names) queued.set(group, (names = new Set()));
  names.add(name);
}

export function requestMedia(kind: MediaKind, sport: string, name: string) {
  if (!name || !sport || cache.has(keyOf(kind, sport, name))) return;
  enqueue(kind, sport, name);
  schedule();
}

// Splits "Away at Home" (the API's game name) or "Away @ Home". Returns null for anything else.
export function splitMatchup(text: string): [string, string] | null {
  const parts = text.split(/ (?:at|@) /);
  return parts.length === 2 && parts[0] && parts[1]
    ? [parts[0], parts[1]]
    : null;
}

const SKIP = new Set(["fc", "afc", "cf", "sc", "ac", "the", "of", "de", "fk"]);
export function initials(name: string, kind: MediaKind) {
  const words = name
    .replace(/[^\p{L}\p{N}\s'-]/gu, " ")
    .split(/\s+/)
    .filter(Boolean);
  const useful = words.filter((w) => !SKIP.has(w.toLowerCase()));
  const pool = useful.length ? useful : words;
  if (!pool.length) return "?";
  if (pool.length === 1) return pool[0].slice(0, 2).toUpperCase();
  const first = pool[0][0];
  const last = pool[pool.length - 1][0];
  return (first + last).toUpperCase();
}

export function hue(name: string) {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) % 360;
  return h;
}

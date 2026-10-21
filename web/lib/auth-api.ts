export interface User {
  id: string;
  username: string;
  role?: "admin" | "member";
  access_kind?: "operator" | "paid_beta" | "preview";
  founder?: boolean;
  cohort?: "beta" | "friend" | "family";
  friend_rates?: {
    standard_usd_cents: number;
    live_usd_cents: number;
    locked: boolean;
  } | null;
  membership?: {
    state: string;
    expires_at: number | null;
    allowed: boolean;
    enforced: boolean;
  };
}

export class AuthRequestError extends Error {
  constructor(
    message: string,
    readonly status = 0,
  ) {
    super(message);
  }
}

const BASE = "/api/refresh/v1/auth";
const EVENT = "corner:unauthorized";

// Recheck the account after a denied request: membership expiry is not a lost login.
export const notifyUnauthorized = () => {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(EVENT));
};
export function onUnauthorized(listener: () => void): () => void {
  window.addEventListener(EVENT, listener);
  return () => window.removeEventListener(EVENT, listener);
}

async function call(
  method: "GET" | "POST",
  path: string,
  body?: unknown,
): Promise<User | null> {
  let response: Response;
  try {
    response = await fetch(`${BASE}/${path}`, {
      method,
      cache: "no-store",
      credentials: "same-origin",
      ...(body !== undefined && {
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
      signal: AbortSignal.timeout(20000),
    });
  } catch {
    throw new AuthRequestError(
      "Could not reach the sign-in service. Please try again shortly.",
    );
  }
  const data = await response.json().catch(() => null);
  if (response.status === 401 && path === "password") notifyUnauthorized();
  if (!response.ok)
    throw new AuthRequestError(
      (data && typeof data.error === "string" && data.error) ||
        "Something went wrong. Try again.",
      response.status,
    );
  return (data?.user as User | undefined) ?? null;
}

// null means "not signed in"; any other failure (service down) throws.
export async function fetchMe(): Promise<User | null> {
  try {
    return await call("GET", "me");
  } catch (e) {
    if (e instanceof AuthRequestError && e.status === 401) return null;
    throw e;
  }
}
// remember: a 30-day cookie; otherwise the session ends when the browser closes (or after 12 hours).
export const signIn = (username: string, password: string, remember: boolean) =>
  call("POST", "login", { username, password, remember }) as Promise<User>;
export const signUp = (
  username: string,
  password: string,
  remember: boolean,
  invite?: string,
) =>
  call("POST", "register", {
    username,
    password,
    remember,
    invite,
  }) as Promise<User>;
export const signOut = () => call("POST", "logout", {}).then(() => undefined);
export const signOutEverywhere = () =>
  call("POST", "logout-all", {}).then(() => {
    notifyUnauthorized();
  });
// A wrong current password comes back as 403, which is shown as a message, not treated as a lost session.
export const changePassword = (current: string, next: string) =>
  call("POST", "password", { current, new: next }).then(() => undefined);

// Only same-site paths are honoured, so a crafted ?next= cannot send someone to another site.
export function safeNext(value: string | null | undefined): string {
  return value && /^\/(?![/\\])[\w\-./?=&%]*$/.test(value) && value !== "/login"
    ? value
    : "/";
}

export const USERNAME_HINT =
  "3-24 characters: letters, numbers, dots, dashes, underscores.";
export const USERNAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{2,23}$/;
export const PASSWORD_MIN = 8;

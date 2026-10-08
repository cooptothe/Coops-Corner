export interface User {
  id: string;
  username: string;
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

// Any service call that comes back 401 (an expired or removed session) sends the user to sign in again.
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
      "Cannot reach the account service. Start it with: python -m pipelines.refresh_service",
    );
  }
  const data = await response.json().catch(() => null);
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
export const signIn = (username: string, password: string) =>
  call("POST", "login", { username, password }) as Promise<User>;
export const signUp = (username: string, password: string) =>
  call("POST", "register", { username, password }) as Promise<User>;
export const signOut = () => call("POST", "logout", {}).then(() => undefined);

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

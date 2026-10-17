"use client";
import { ParlayProvider } from "./parlay-builder";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import Image from "next/image";
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
import {
  AccountRecheck,
  needsMembershipAccount,
  membershipRouteAllowed,
} from "../lib/membership-access";
import { setStorageOwner } from "../lib/user-storage";
import { SettingsProvider } from "./settings-provider";
import {
  fetchMe,
  onUnauthorized,
  signIn,
  signOut,
  signUp,
  type User,
} from "../lib/auth-api";

type Status = "loading" | "signed-in" | "signed-out" | "unreachable";

interface Auth {
  status: Status;
  user: User | null;
  login: (
    username: string,
    password: string,
    remember: boolean,
  ) => Promise<void>;
  register: (
    username: string,
    password: string,
    remember: boolean,
    invite?: string,
  ) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<Auth | null>(null);

export function useAuth(): Auth {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [user, setUser] = useState<User | null>(null);
  const [attempt, setAttempt] = useState(0);

  const recheck = useRef<AccountRecheck | null>(null);
  if (!recheck.current)
    recheck.current = new AccountRecheck(
      fetchMe,
      (me) => {
        setStorageOwner(me?.id ?? null);
        setUser(me);
        setStatus(me ? "signed-in" : "signed-out");
      },
      () => setStatus("unreachable"),
    );

  useEffect(() => {
    void recheck.current!.check();
    return () => recheck.current!.invalidate();
  }, [attempt]);

  useEffect(
    () =>
      onUnauthorized(() => {
        void recheck.current!.check();
      }),
    [],
  );

  useEffect(() => {
    if (status !== "signed-in" || !user?.membership?.enforced) return;
    const refresh = () => {
      if (document.visibilityState !== "hidden") void recheck.current!.check();
    };
    const interval = setInterval(refresh, 60000);
    const expiry = user.membership.expires_at;
    const remaining = expiry === null ? null : expiry * 1000 - Date.now();
    const deadline =
      remaining !== null && remaining > 0 && remaining <= 2147483647
        ? setTimeout(
            () => {
              // Remove feed content at the known deadline even if the server is unreachable.
              setUser((current) =>
                current?.id === user.id && current.membership
                  ? {
                      ...current,
                      membership: {
                        ...current.membership,
                        allowed: false,
                        state: "expired",
                      },
                    }
                  : current,
              );
              refresh();
            },
            Math.min(remaining, 2147483647),
          )
        : null;
    document.addEventListener("visibilitychange", refresh);
    window.addEventListener("focus", refresh);
    return () => {
      clearInterval(interval);
      if (deadline !== null) clearTimeout(deadline);
      document.removeEventListener("visibilitychange", refresh);
      window.removeEventListener("focus", refresh);
    };
  }, [status, user]);

  const accept = useCallback((me: User) => {
    recheck.current!.invalidate();
    setStorageOwner(me.id);
    setUser(me);
    setStatus("signed-in");
  }, []);
  const value = useMemo<Auth>(
    () => ({
      status,
      user,
      login: async (username, password, remember) => {
        recheck.current!.invalidate();
        accept(await signIn(username, password, remember));
      },
      register: async (username, password, remember, invite) => {
        recheck.current!.invalidate();
        accept(await signUp(username, password, remember, invite));
      },
      logout: async () => {
        recheck.current!.invalidate();
        setStorageOwner(null);
        setUser(null);
        setStatus("signed-out");
        // Clear locally even if the request fails, so the screen never stays signed in by mistake.
        await signOut().catch(() => undefined);
        recheck.current!.invalidate();
        setStorageOwner(null);
        setUser(null);
        setStatus("signed-out");
      },
    }),
    [status, user, accept],
  );

  return (
    <AuthContext.Provider value={value}>
      {status === "unreachable" ? (
        <Splash>
          <p role="alert">
            Your workspace is temporarily unavailable. Please try again shortly.
          </p>
          <p>
            Your saved account and preferences will be here when you reconnect.
          </p>
          <button
            className="button"
            onClick={() => {
              setStatus("loading");
              setAttempt((n) => n + 1);
            }}
          >
            Reconnect
          </button>
        </Splash>
      ) : (
        children
      )}
    </AuthContext.Provider>
  );
}

export function Splash({ children }: { children?: ReactNode }) {
  return (
    <div className="auth-splash" role="status" aria-live="polite">
      <Image
        src="/assets/corner-logo.png"
        alt="Coop's Corner"
        width={96}
        height={96}
        priority
      />
      {children ?? <p>Loading…</p>}
    </div>
  );
}

// Everything except the sign-in page needs a session. Protected pages are not even rendered until the
// server has confirmed one, so a signed-out visitor never triggers their data requests.
export function AuthGate({ children }: { children: ReactNode }) {
  const { status, user } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const isLogin = pathname === "/login";
  const membershipBlocked =
    status === "signed-in" &&
    needsMembershipAccount(user) &&
    !membershipRouteAllowed(pathname);

  useEffect(() => {
    if (membershipBlocked) {
      router.replace("/account");
    } else if (status === "signed-out" && !isLogin) {
      const next =
        pathname && pathname !== "/"
          ? `?next=${encodeURIComponent(pathname)}`
          : "";
      router.replace(`/login${next}`);
    }
  }, [status, isLogin, pathname, router, membershipBlocked]);

  if (membershipBlocked)
    return (
      <Splash>
        <p>Your membership access has ended or has not started.</p>
        <p>
          <Link href="/account">View membership</Link> |{" "}
          <Link href="/tracker">Open your tracker</Link>
        </p>
      </Splash>
    );
  if (status === "unreachable") return null;
  if (status === "loading") return <Splash />;
  if (status === "signed-out" && !isLogin) return <Splash />;
  if (status === "signed-in" && user && !isLogin)
    return (
      <SettingsProvider key={user.id}>
        <ParlayProvider>{children}</ParlayProvider>
      </SettingsProvider>
    );
  return <>{children}</>;
}

export function UserMenu() {
  const { user, logout } = useAuth();
  const [busy, setBusy] = useState(false);
  if (!user) return null;
  return (
    <span className="user-menu">
      <Link className="user-chip" href="/account" title="Your account">
        <span className="user-avatar" aria-hidden="true">
          {user.username.slice(0, 1).toUpperCase()}
        </span>
        {user.username}
      </Link>
      <button
        type="button"
        className="button secondary"
        disabled={busy}
        onClick={() => {
          setBusy(true);
          logout().finally(() => setBusy(false));
        }}
      >
        Sign out
      </button>
    </span>
  );
}

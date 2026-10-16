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
  useState,
  type ReactNode,
} from "react";
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

  // Hydrate once per page load: the cookie is HttpOnly, so the server is the only one who can say who we are.
  useEffect(() => {
    let live = true;
    fetchMe().then(
      (me) => {
        if (!live) return;
        setStorageOwner(me?.id ?? null);
        setUser(me);
        setStatus(me ? "signed-in" : "signed-out");
      },
      () => live && setStatus("unreachable"),
    );
    return () => {
      live = false;
    };
  }, [attempt]);

  useEffect(
    () =>
      onUnauthorized(() => {
        setStorageOwner(null);
        setUser(null);
        setStatus("signed-out");
      }),
    [],
  );

  const accept = useCallback((me: User) => {
    setStorageOwner(me.id);
    setUser(me);
    setStatus("signed-in");
  }, []);
  const value = useMemo<Auth>(
    () => ({
      status,
      user,
      login: async (username, password, remember) =>
        accept(await signIn(username, password, remember)),
      register: async (username, password, remember, invite) =>
        accept(await signUp(username, password, remember, invite)),
      logout: async () => {
        // Clear locally even if the request fails, so the screen never stays signed in by mistake.
        await signOut().catch(() => undefined);
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
            Your workspace is offline. Start The Corner, then try connecting
            again.
          </p>
          <p>
            On this computer, double-click <strong>Start-Corner.cmd</strong> in
            your app folder.
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

  useEffect(() => {
    if (status === "signed-out" && !isLogin) {
      const next =
        pathname && pathname !== "/"
          ? `?next=${encodeURIComponent(pathname)}`
          : "";
      router.replace(`/login${next}`);
    }
  }, [status, isLogin, pathname, router]);

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

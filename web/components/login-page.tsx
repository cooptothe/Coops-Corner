"use client";
import Image from "next/image";
import { invitationToken } from "../lib/invitation-api";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import {
  PASSWORD_MIN,
  USERNAME_HINT,
  USERNAME_PATTERN,
  safeNext,
} from "../lib/auth-api";
import { useAuth } from "./auth-provider";

type Mode = "signin" | "signup";
const REMEMBER_KEY = "corner.remember-me";

export default function LoginPage() {
  const { status, login, register } = useAuth();
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("signin");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [invite, setInvite] = useState("");
  const [show, setShow] = useState(false);
  const [remember, setRemember] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // Already signed in (or just became so): go where the visitor was headed.
  useEffect(() => {
    if (status === "signed-in") {
      const next = safeNext(
        new URLSearchParams(window.location.search).get("next"),
      );
      router.replace(next);
    }
  }, [status, router]);

  useEffect(() => {
    document.title = "Sign in — The Corner";
    const invitation = invitationToken(window.location.hash);
    if (invitation) {
      setMode("signup");
      setInvite(invitation);
      window.history.replaceState(
        null,
        "",
        window.location.pathname + window.location.search,
      );
    }
    // Only the checkbox choice is remembered here, never any credentials.
    try {
      setRemember(localStorage.getItem(REMEMBER_KEY) === "1");
    } catch {}
  }, []);

  const signup = mode === "signup";
  const switchMode = (next: Mode) => {
    setMode(next);
    setError("");
    setConfirm("");
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    const name = username.trim();
    if (signup && !USERNAME_PATTERN.test(name))
      return setError(`Username: ${USERNAME_HINT}`);
    if (!name) return setError("Enter your username.");
    if (signup && password.length < PASSWORD_MIN)
      return setError(`Passwords must be at least ${PASSWORD_MIN} characters.`);
    if (!password) return setError("Enter your password.");
    if (signup && password !== confirm)
      return setError("The two passwords do not match.");
    setBusy(true);
    setError("");
    try {
      try {
        localStorage.setItem(REMEMBER_KEY, remember ? "1" : "0");
      } catch {}
      await (signup
        ? register(name, password, remember, invite.trim())
        : login(name, password, remember));
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Something went wrong. Try again.",
      );
      setPassword("");
      setConfirm("");
      setBusy(false);
    }
  };

  if (status === "signed-in") return null;

  return (
    <main className="auth-page">
      <section className="auth-card" aria-labelledby="auth-title">
        <Image
          className="auth-banner"
          src="/assets/corner-banner.png"
          alt="Coop's Corner"
          width={1500}
          height={500}
          sizes="(max-width: 600px) 320px, 420px"
          priority
        />
        <p className="eyebrow">THE COMMUNITY. THE INTELLIGENCE. THE EDGE.</p>
        <h1 id="auth-title">
          {signup ? "Create your account" : "Welcome back"}
        </h1>
        <div className="arb-modes auth-tabs" role="group" aria-label="Account">
          <button
            type="button"
            className={!signup ? "active" : ""}
            disabled={busy}
            aria-pressed={!signup}
            onClick={() => switchMode("signin")}
          >
            Sign in
          </button>
          <button
            type="button"
            className={signup ? "active" : ""}
            disabled={busy}
            aria-pressed={signup}
            onClick={() => switchMode("signup")}
          >
            Create account
          </button>
        </div>
        <form onSubmit={submit} noValidate>
          {signup && (
            <label className="field">
              <span>INVITATION CODE</span>
              <input
                value={invite}
                onChange={(e) => setInvite(e.target.value)}
                autoComplete="off"
                autoCapitalize="none"
                spellCheck={false}
                maxLength={200}
              />
              <small>
                Use your private invitation code. Choose your username when you
                create your account.
              </small>
            </label>
          )}
          <label className="field">
            <span>USERNAME</span>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              maxLength={24}
              autoFocus
              required
            />
            {signup && <small>{USERNAME_HINT} Usernames are unique.</small>}
          </label>
          <div className="field">
            <label htmlFor="auth-password">PASSWORD</label>
            <span className="auth-password">
              <input
                id="auth-password"
                type={show ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={signup ? "new-password" : "current-password"}
                maxLength={128}
                required
              />
              <button
                type="button"
                className="link-button"
                onClick={() => setShow((s) => !s)}
                aria-pressed={show}
              >
                {show ? "Hide" : "Show"}
              </button>
            </span>
            {signup && <small>At least {PASSWORD_MIN} characters.</small>}
          </div>{" "}
          {signup && (
            <label className="field">
              <span>CONFIRM PASSWORD</span>
              <input
                type={show ? "text" : "password"}
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="new-password"
                maxLength={128}
                required
              />
            </label>
          )}
          <label className="auth-remember">
            <input
              type="checkbox"
              checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
            />
            <span>
              Remember me
              <small>
                {remember
                  ? "Stay signed in on this device for 30 days."
                  : "Sign out when you close the browser. Use on shared computers."}
              </small>
            </span>
          </label>
          {error && (
            <div role="alert" className="arb-alert">
              <span>{error}</span>
            </div>
          )}
          <button className="button auth-submit" type="submit" disabled={busy}>
            {busy
              ? signup
                ? "Creating account…"
                : "Signing in…"
              : signup
                ? "Create account"
                : "Sign in"}
          </button>
        </form>
        <p className="auth-foot">
          {signup ? "Already have an account? " : "New here? "}
          <button
            type="button"
            className="link-button"
            onClick={() => switchMode(signup ? "signin" : "signup")}
          >
            {signup ? "Sign in" : "Create an account"}
          </button>
        </p>
        <p className="auth-fine">
          Need help signing in?{" "}
          <a href="mailto:admin@coopscorner.tech">Contact support</a>.
        </p>
        <p className="auth-fine">
          Your bets and bankroll are private to your account. This site never
          places wagers.
        </p>
      </section>
    </main>
  );
}

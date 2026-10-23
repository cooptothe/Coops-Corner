"use client";
import { PersonalNav } from "./personal-nav";
import Image from "next/image";
import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import {
  PASSWORD_MIN,
  changePassword,
  signOutEverywhere,
} from "../lib/auth-api";
import { UserMenu, useAuth } from "./auth-provider";
import { StatePicker } from "./bet-link";
import BetaMembership from "./beta-membership";

export default function AccountPage() {
  const { user } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const [sessionsBusy, setSessionsBusy] = useState(false);
  const [sessionsError, setSessionsError] = useState("");

  useEffect(() => {
    document.title = "Account — The Corner";
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setDone(false);
    if (!current) return setError("Enter your current password.");
    if (next.length < PASSWORD_MIN)
      return setError(
        `New passwords must be at least ${PASSWORD_MIN} characters.`,
      );
    if (next !== confirm)
      return setError("The two new passwords do not match.");
    setBusy(true);
    setError("");
    try {
      await changePassword(current, next);
      setCurrent("");
      setNext("");
      setConfirm("");
      setDone(true);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Something went wrong. Try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <main id="main" tabIndex={-1} className="personal-workspace account-page">
      <header className="personal-header page-header">
        <Link href="/games">
          <Image
            src="/assets/corner-logo.png"
            width={64}
            height={64}
            alt="Coop's Corner"
          />
        </Link>
        <div>
          <p className="eyebrow">YOUR CORNER</p>
          <h1>Account</h1>
        </div>
        <div className="page-actions">
          <Link className="button secondary" href="/positive_ev">
            ← Back to tools
          </Link>
          <UserMenu />
        </div>
      </header>
      <PersonalNav current="account" />
      <BetaMembership />
      <section className="trk-card account-card" aria-labelledby="state-title">
        <h3 id="state-title">Betting state</h3>
        <p className="trk-muted">Choose your state for sportsbook links.</p>
        <StatePicker />
      </section>
      <section
        className="trk-card account-card"
        aria-labelledby="session-title"
      >
        <h3 id="session-title">Device sessions</h3>
        <p className="trk-muted">
          Sign out every device, including this one. You will need to sign in
          again.
        </p>
        {sessionsError && <p role="alert">{sessionsError}</p>}
        <button
          type="button"
          className="button"
          disabled={sessionsBusy}
          onClick={async () => {
            setSessionsBusy(true);
            setSessionsError("");
            try {
              await signOutEverywhere();
            } catch {
              setSessionsError("Could not sign out devices. Please try again.");
            } finally {
              setSessionsBusy(false);
            }
          }}
        >
          {sessionsBusy ? "Signing out…" : "Sign out everywhere"}
        </button>
      </section>
      <section className="trk-card account-card" aria-labelledby="pw-title">
        <h3 id="pw-title">Change password</h3>
        <p className="trk-muted">
          Signed in as <strong>{user?.username}</strong>. Changing your password
          signs out every other device. Forgot it instead?{" "}
          <a href="mailto:admin@coopscorner.tech">Contact support</a> for help
          recovering your account.
        </p>
        <form onSubmit={submit} noValidate className="account-form">
          <div className="field">
            <label htmlFor="pw-current">CURRENT PASSWORD</label>
            <input
              id="pw-current"
              type="password"
              value={current}
              autoComplete="current-password"
              maxLength={128}
              onChange={(e) => setCurrent(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="pw-new">NEW PASSWORD</label>
            <input
              id="pw-new"
              type="password"
              value={next}
              autoComplete="new-password"
              maxLength={128}
              onChange={(e) => setNext(e.target.value)}
            />
            <small>At least {PASSWORD_MIN} characters.</small>
          </div>
          <div className="field">
            <label htmlFor="pw-confirm">CONFIRM NEW PASSWORD</label>
            <input
              id="pw-confirm"
              type="password"
              value={confirm}
              autoComplete="new-password"
              maxLength={128}
              onChange={(e) => setConfirm(e.target.value)}
            />
          </div>
          {error && (
            <div role="alert" className="arb-alert">
              <span>{error}</span>
            </div>
          )}
          {done && (
            <p role="status" className="account-ok">
              Password changed. Other devices have been signed out.
            </p>
          )}
          <button className="button" type="submit" disabled={busy}>
            {busy ? "Saving…" : "Change password"}
          </button>
        </form>
      </section>
      <Link className="tool-help" href="/help#install">
        Mobile setup &amp; troubleshooting
      </Link>
    </main>
  );
}

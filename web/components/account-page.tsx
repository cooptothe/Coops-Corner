"use client";
import { PersonalNav } from "./personal-nav";
import Image from "next/image";
import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { PASSWORD_MIN, changePassword } from "../lib/auth-api";
import { UserMenu, useAuth } from "./auth-provider";
import { StatePicker } from "./bet-link";

export default function AccountPage() {
  const { user } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

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
    <main className="personal-workspace account-page">
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
      <section className="trk-card account-card" aria-labelledby="state-title">
        <h3 id="state-title">Betting state</h3>
        <p className="trk-muted">
          Some sportsbooks, such as BetMGM and BetRivers, have a separate site
          for each state. Choose yours so “Bet on” links open the right one. It
          is saved to your account.
        </p>
        <StatePicker />
      </section>
      <section className="trk-card account-card" aria-labelledby="pw-title">
        <h3 id="pw-title">Change password</h3>
        <p className="trk-muted">
          Signed in as <strong>{user?.username}</strong>. Changing your password
          signs out every other device. Forgot it instead? Ask whoever runs this
          app to reset it for you.
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
    </main>
  );
}

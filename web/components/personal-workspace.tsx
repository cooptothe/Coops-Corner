"use client";
import Link from "next/link";
import Image from "next/image";
import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  american,
  americanToDecimal,
  fixed,
  usd,
  date,
} from "../../frontend/format.mjs";

type Profile = { id: string; username: string; csrf_token: string };
type RecordRow = {
  id: string;
  description: string;
  sportsbook: string;
  stake: string;
  returned: string;
  decimal_odds: string;
  placed_at: string;
  settled_at: string;
};
type CashRow = {
  id: string;
  kind: string;
  amount: string;
  note: string;
  occurred_at: string;
};
type Dashboard = {
  summary: {
    record_count: number;
    total_staked: string;
    total_returned: string;
    net_profit: string;
    deposits: string;
    withdrawals: string;
    recorded_balance: string;
  };
  records: RecordRow[];
  cash_entries: CashRow[];
  offset: number;
  limit: number;
  currency: "USD";
  mode: "manual_retrospective";
};
class PersonalError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}
async function api<T>(
  path: string,
  body?: Record<string, string>,
  csrf?: string,
): Promise<T> {
  const response = await fetch("/api/account/v1/" + path, {
    method: body ? "POST" : "GET",
    credentials: "same-origin",
    cache: "no-store",
    signal: AbortSignal.timeout(10000),
    headers: body
      ? {
          "Content-Type": "application/json",
          "X-Corner-Request": "1",
          ...(csrf ? { "X-CSRF-Token": csrf } : {}),
        }
      : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const result = await response.json().catch(() => {
    throw new PersonalError(
      "Account service is unavailable. Nothing has been assumed saved.",
      response.status,
    );
  });
  if (!response.ok)
    throw new PersonalError(
      result.error?.message ?? "Unable to access personal records.",
      response.status,
    );
  return result as T;
}
function Field({
  name,
  label,
  type = "text",
  ...rest
}: {
  name: string;
  label: string;
  type?: string;
  [key: string]: unknown;
}) {
  return (
    <label>
      {label}
      <input name={name} type={type} required {...rest} />
    </label>
  );
}
export default function PersonalWorkspace() {
  const [profile, setProfile] = useState<Profile | null>(null),
    [data, setData] = useState<Dashboard | null>(null);
  const [ready, setReady] = useState(false),
    [register, setRegister] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [offset, setOffset] = useState(0);
  const recordKey = useRef(""),
    cashKey = useRef("");
  function failure(e: unknown) {
    setError(e instanceof Error ? e.message : "Unable to complete request.");
    if (e instanceof PersonalError && e.status === 401) {
      setProfile(null);
      setData(null);
    }
  }
  async function load(page = offset) {
    setData(await api<Dashboard>("records?offset=" + page));
  }
  useEffect(() => {
    let live = true;
    api<Profile>("session")
      .then((p) => {
        if (live) setProfile(p);
      })
      .catch((e) => {
        if (live && (!(e instanceof PersonalError) || e.status !== 401))
          failure(e);
      })
      .finally(() => {
        if (live) setReady(true);
      });
    return () => {
      live = false;
    };
  }, []);
  useEffect(() => {
    if (!profile) return;
    let live = true;
    setData(null);
    api<Dashboard>("records?offset=" + offset)
      .then((d) => {
        if (live) setData(d);
      })
      .catch((e) => {
        if (live) failure(e);
      });
    return () => {
      live = false;
    };
  }, [profile, offset]);
  async function authenticate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const form = event.currentTarget;
    try {
      const input = Object.fromEntries(new FormData(form)) as Record<
        string,
        string
      >;
      setProfile(await api<Profile>(register ? "register" : "login", input));
      form.reset();
      setOffset(0);
    } catch (e) {
      failure(e);
    } finally {
      setBusy(false);
    }
  }
  async function save(event: FormEvent<HTMLFormElement>, cash: boolean) {
    event.preventDefault();
    if (!profile) return;
    setBusy(true);
    setError("");
    setNotice("");
    const form = event.currentTarget;
    const key = cash ? cashKey : recordKey;
    try {
      const input = Object.fromEntries(new FormData(form)) as Record<
        string,
        string
      >;
      if (!key.current) key.current = crypto.randomUUID();
      input.request_key = key.current;
      if (cash) {
        input.occurred_at = new Date(input.occurred_at).toISOString();
      } else {
        input.decimal_odds = fixed(americanToDecimal(input.american_odds), 8);
        delete input.american_odds;
        input.placed_at = new Date(input.placed_at).toISOString();
        input.settled_at = new Date(input.settled_at).toISOString();
      }
      await api(cash ? "cash" : "records", input, profile.csrf_token);
      form.reset();
      key.current = "";
      setNotice("Record saved. No money was moved and no bet was placed.");
      await load();
    } catch (e) {
      failure(e);
    } finally {
      setBusy(false);
    }
  }
  async function logout() {
    if (!profile) return;
    setBusy(true);
    setError("");
    try {
      await api("logout", {}, profile.csrf_token);
      setProfile(null);
      setData(null);
      setNotice("");
    } catch (e) {
      failure(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="personal-workspace">
      <header className="personal-header">
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
          <h1>Tracker &amp; bankroll</h1>
        </div>
        <Link href="/games">Upcoming schedule →</Link>
      </header>
      <p className="personal-disclaimer">
        Private records of completed activity. Manual entries only—no sportsbook
        connection, transfers, wager placement, or automatic grading.
      </p>
      {error && (
        <div className="error-card" role="alert">
          {error}
        </div>
      )}
      {notice && <p role="status">{notice}</p>}
      {!ready ? (
        <p>Checking your session…</p>
      ) : !profile ? (
        <section className="personal-card auth-card">
          <h2>{register ? "Create your local account" : "Welcome back"}</h2>
          <p>
            This account is for The Corner, not a sportsbook. Do not reuse a
            sportsbook password.
          </p>
          <form onSubmit={authenticate}>
            <Field
              name="username"
              label="Username"
              minLength={3}
              maxLength={40}
              pattern="[A-Za-z0-9_]{3,40}"
              autoComplete="username"
            />
            <Field
              name="password"
              label="Password (12+ characters)"
              type="password"
              minLength={12}
              maxLength={72}
              autoComplete={register ? "new-password" : "current-password"}
            />
            <button className="button" disabled={busy}>
              {busy ? "Please wait…" : register ? "Create account" : "Sign in"}
            </button>
          </form>
          <button
            className="personal-link"
            disabled={busy}
            onClick={() => {
              setRegister(!register);
              setError("");
            }}
          >
            {register
              ? "Already have an account? Sign in"
              : "Create an account"}
          </button>
          <p className="personal-muted">
            Local preview only. Password recovery and multi-factor
            authentication are not enabled.
          </p>
        </section>
      ) : (
        <>
          <div className="personal-session">
            <span>
              Signed in as <strong>{profile.username}</strong>
            </span>
            <button className="button" disabled={busy} onClick={logout}>
              Sign out
            </button>
          </div>
          {data ? (
            <section className="personal-summary" aria-label="Recorded totals">
              {[
                ["Recorded balance", data.summary.recorded_balance],
                ["Net settled profit/loss", data.summary.net_profit],
                ["Total staked", data.summary.total_staked],
                ["Returned, including stake", data.summary.total_returned],
              ].map(([label, value]) => (
                <div className="personal-card" key={label}>
                  <span>{label}</span>
                  <strong>{usd(value)}</strong>
                </div>
              ))}
            </section>
          ) : (
            <p>Loading your records…</p>
          )}
          <p className="personal-muted">
            Recorded balance = deposits − withdrawals + settled profit/loss. It
            excludes open wagers and unrecorded activity; it is not a verified
            account balance.
          </p>
          <div className="personal-forms">
            <section className="personal-card">
              <h2>Record a settled bet</h2>
              <p>
                Enter the actual settled amounts from your records. Returned
                amount includes any stake returned; enter $0.00 for a complete
                loss.
              </p>
              <form
                onSubmit={(e) => save(e, false)}
                onChange={() => {
                  recordKey.current = "";
                }}
              >
                <Field
                  name="description"
                  label="Event / market / selection"
                  maxLength={300}
                />
                <Field name="sportsbook" label="Sportsbook" maxLength={100} />
                <div className="personal-pair">
                  <Field
                    name="stake"
                    label="Actual stake ($ USD)"
                    inputMode="decimal"
                    pattern="[0-9]+(\.[0-9]{1,2})?"
                  />
                  <Field
                    name="returned"
                    label="Actual total returned ($ USD)"
                    inputMode="decimal"
                    pattern="[0-9]+(\.[0-9]{1,2})?"
                  />
                </div>
                <Field
                  name="american_odds"
                  label="Recorded American odds"
                  placeholder="+150 or -110"
                  pattern="[+\-][0-9]{3,9}"
                />
                <div className="personal-pair">
                  <Field
                    name="placed_at"
                    label="Placed at (your local time)"
                    type="datetime-local"
                  />
                  <Field
                    name="settled_at"
                    label="Settled at (your local time)"
                    type="datetime-local"
                  />
                </div>
                <button className="button" disabled={busy}>
                  Save settled record
                </button>
              </form>
            </section>
            <section className="personal-card">
              <h2>Record a cash movement</h2>
              <p>
                Bookkeeping only. This form does not deposit or withdraw money.
              </p>
              <form
                onSubmit={(e) => save(e, true)}
                onChange={() => {
                  cashKey.current = "";
                }}
              >
                <label>
                  Type
                  <select name="kind">
                    <option value="deposit">Deposit</option>
                    <option value="withdrawal">Withdrawal</option>
                  </select>
                </label>
                <Field
                  name="amount"
                  label="Amount ($ USD)"
                  inputMode="decimal"
                  pattern="[0-9]+(\.[0-9]{1,2})?"
                />
                <Field
                  name="occurred_at"
                  label="Occurred at (your local time)"
                  type="datetime-local"
                />
                <label>
                  Note (optional)
                  <input name="note" maxLength={300} />
                </label>
                <button className="button" disabled={busy}>
                  Save cash record
                </button>
              </form>
              <h3>CLV coverage</h3>
              <p className="personal-muted">
                Not available yet. A single market snapshot cannot establish a
                closing line. No current or latest price will be mislabeled as a
                verified closing benchmark.
              </p>
            </section>
          </div>
          {data && (
            <>
              <section className="personal-card">
                <h2>Settled history · {data.summary.record_count} records</h2>
                <div className="personal-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Event / selection</th>
                        <th>Book</th>
                        <th>Odds</th>
                        <th>Stake</th>
                        <th>Returned</th>
                        <th>Settled (UTC)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.records.map((r) => (
                        <tr key={r.id}>
                          <td>{r.description}</td>
                          <td>{r.sportsbook}</td>
                          <td>{american(r.decimal_odds)}</td>
                          <td>{usd(r.stake)}</td>
                          <td>{usd(r.returned)}</td>
                          <td>{date(r.settled_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {!data.records.length && (
                  <p>No settled records on this page.</p>
                )}
              </section>
              <section className="personal-card">
                <h2>Cash history</h2>
                {data.cash_entries.map((r) => (
                  <p key={r.id}>
                    {r.kind} · {usd(r.amount)} · {date(r.occurred_at)} ·{" "}
                    {r.note}
                  </p>
                ))}
                {!data.cash_entries.length && (
                  <p>No cash records on this page.</p>
                )}
              </section>
              <div className="personal-session">
                <button
                  className="button"
                  disabled={offset === 0 || busy}
                  onClick={() => setOffset(Math.max(0, offset - 50))}
                >
                  Previous
                </button>
                <span>Page {offset / 50 + 1} · 50 records per list</span>
                <button
                  className="button"
                  disabled={
                    busy ||
                    (data.records.length < 50 && data.cash_entries.length < 50)
                  }
                  onClick={() => setOffset(offset + 50)}
                >
                  Next
                </button>
              </div>
            </>
          )}
        </>
      )}
    </main>
  );
}

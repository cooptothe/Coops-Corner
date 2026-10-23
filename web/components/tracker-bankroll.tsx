"use client";
import { useMemo, useRef, useState } from "react";
import { usd } from "../../frontend/format.mjs";
import type {
  CashEntry,
  CashKind,
  NewCashBody,
  TrackerBet,
} from "../lib/tracker-api";
import {
  VAULT,
  bookBalances,
  bookCode,
  bookLabel,
  dailySeries,
  dollars,
  drawdown,
  kpis,
  ledger,
  parseDollars,
  signedDollars,
  signedPercent,
  totals,
} from "../lib/tracker-math";
import { LineChart } from "./tracker-chart";
import { when } from "./tracker-parts";

import { PERFORMANCE_WINDOWS, performanceBounds } from "../lib/tracker-windows";

const money = (cents: number) => usd(dollars(cents));

const KIND_LABEL: Record<string, string> = {
  DEPOSIT: "Deposit",
  WITHDRAWAL: "Withdrawal",
  BOOK_TRANSFER: "Transfer",
  ADJUSTMENT: "Adjustment",
  WAGER_DEDUCTION: "Wager placed",
  WAGER_PAYOUT: "Wager settled",
};

function localToday() {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function CashForm({
  onSubmit,
}: {
  onSubmit: (body: NewCashBody) => Promise<void>;
}) {
  const [kind, setKind] = useState<CashKind>("deposit");
  const [book, setBook] = useState("");
  const [toBook, setToBook] = useState("");
  const [amount, setAmount] = useState("");
  const [day, setDay] = useState(localToday());
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const attempt = useRef(crypto.randomUUID());
  const submit = async () => {
    setError("");
    setSaved("");
    const cents = parseDollars(amount);
    if (!book.trim()) return setError("Choose where the money is.");
    if (kind === "transfer" && !toBook.trim())
      return setError("Choose where the money is going.");
    if (cents == null || cents === 0 || (kind !== "adjustment" && cents < 0))
      return setError(
        kind === "adjustment"
          ? "Enter a dollar amount (negative reduces the balance)."
          : "Enter a positive dollar amount, such as 100 or 100.50.",
      );
    let occurred: string | undefined;
    if (day && day !== localToday()) {
      const d = new Date(`${day}T12:00:00`);
      if (Number.isNaN(d.getTime())) return setError("The date is not valid.");
      occurred = d.toISOString();
    }
    setBusy(true);
    try {
      await onSubmit({
        client_key: `ui:${attempt.current}`,
        kind,
        book: bookCode(book),
        ...(kind === "transfer" && { to_book: bookCode(toBook) }),
        amount: dollars(cents),
        ...(occurred && { occurred_at: occurred }),
        note: note.trim(),
      });
      attempt.current = crypto.randomUUID();
      setAmount("");
      setNote("");
      setSaved("Saved.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <form
      className="trk-cash"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <label className="field">
        <span>TYPE</span>
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value as CashKind)}
        >
          <option value="deposit">Deposit (money in)</option>
          <option value="withdrawal">Withdrawal (money out)</option>
          <option value="transfer">Rebalance (move between books)</option>
          <option value="adjustment">Adjustment (correct a balance)</option>
        </select>
      </label>
      <label className="field">
        <span>{kind === "transfer" ? "FROM" : "SPORTSBOOK OR VAULT"}</span>
        <input
          value={book}
          list="trk-books"
          placeholder="FanDuel"
          onChange={(e) => setBook(e.target.value)}
        />
      </label>
      {kind === "transfer" && (
        <label className="field">
          <span>TO</span>
          <input
            value={toBook}
            list="trk-books"
            placeholder="DraftKings"
            onChange={(e) => setToBook(e.target.value)}
          />
        </label>
      )}
      <label className="field">
        <span>AMOUNT ($)</span>
        <input
          inputMode="decimal"
          value={amount}
          placeholder="100.00"
          onChange={(e) => setAmount(e.target.value)}
        />
      </label>
      <label className="field">
        <span>DATE</span>
        <input
          type="date"
          value={day}
          max={localToday()}
          onChange={(e) => setDay(e.target.value)}
        />
      </label>
      <label className="field">
        <span>NOTE (OPTIONAL)</span>
        <input
          value={note}
          maxLength={300}
          placeholder="Withdrew sign-up bonus cash"
          onChange={(e) => setNote(e.target.value)}
        />
      </label>
      <button className="button" disabled={busy} type="submit">
        {busy ? "Saving…" : "Add entry"}
      </button>
      {error && (
        <div role="alert" className="arb-alert">
          <span>{error}</span>
        </div>
      )}
      {saved && (
        <small className="kelly-note" role="status">
          {saved}
        </small>
      )}
    </form>
  );
}

const RANGES: [string, number | null][] = [
  ["30d", 30],
  ["90d", 90],
  ["All", null],
];

export function BankrollTab({
  bets,
  cash,
  onAddCash,
  onDeleteCash,
}: {
  bets: TrackerBet[];
  cash: CashEntry[];
  onAddCash: (body: NewCashBody) => Promise<void>;
  onDeleteCash: (id: string) => Promise<void>;
}) {
  const [range, setRange] = useState<number | null>(90);
  const [shown, setShown] = useState(40);
  const [deleteError, setDeleteError] = useState("");
  const state = useMemo(() => ({ bets, cash }), [bets, cash]);
  const rows = useMemo(() => bookBalances(state), [state]);
  const total = useMemo(() => totals(rows), [rows]);
  const entries = useMemo(() => ledger(state).reverse(), [state]);
  const series = useMemo(() => dailySeries(state), [state]);
  const dd = useMemo(() => drawdown(series), [series]);
  const windowed = useMemo(
    () => (range == null ? series : series.slice(-range)),
    [series, range],
  );
  const days = windowed.map((p) => p.day);
  // Profit curves restart at zero for the chosen window; the bankroll curve keeps its real level.
  const base = windowed[0];
  const evBets = bets.filter(
    (b) =>
      b.ev_ratio != null &&
      b.status !== "pending" &&
      b.stake_type === "cash" &&
      b.status !== "void",
  );
  const now = Date.now();
  const windows: [string, ReturnType<typeof kpis>][] = PERFORMANCE_WINDOWS.map(
    ({ value, label }) => [label, kpis(bets, ...performanceBounds(value, now))],
  );
  const vault = rows.find((r) => r.book === VAULT);
  const negative = rows.some((r) => r.liquid < 0);
  return (
    <div className="trk-bankroll">
      <div className="trk-kpis four" aria-label="Bankroll summary">
        <div className="trk-kpi">
          <span>TOTAL BANKROLL</span>
          <strong>{money(total.bankroll)}</strong>
          <small>cash at books + bets in play + vault</small>
        </div>
        <div className="trk-kpi">
          <span>AVAILABLE</span>
          <strong>{money(total.liquid)}</strong>
          <small>ready to bet or withdraw</small>
        </div>
        <div className="trk-kpi">
          <span>IN PLAY</span>
          <strong>{money(total.pending)}</strong>
          <small>stakes on open bets</small>
        </div>
        <div className="trk-kpi">
          <span>VAULT</span>
          <strong>{money(vault?.liquid ?? 0)}</strong>
          <small>unassigned funds</small>
        </div>
      </div>
      {negative && (
        <div role="alert" className="arb-alert">
          <strong>A balance is below zero.</strong>
          <span>
            You logged bets at a book before recording its deposit. Add the
            deposit (or an adjustment) so balances match what the sportsbook
            shows.
          </span>
        </div>
      )}

      <section className="trk-card" aria-label="Performance windows">
        <h3>Performance</h3>
        <div className="trk-windows">
          {windows.map(([label, k]) => (
            <div key={label}>
              <span>{label.toUpperCase()}</span>
              <strong className={k.pnl > 0 ? "pos" : k.pnl < 0 ? "neg" : ""}>
                {signedDollars(k.pnl)}
              </strong>
              <small>
                ROI {signedPercent(k.roi)} · {k.wins}-{k.losses}-{k.pushes} ·{" "}
                {k.settled} settled
              </small>
            </div>
          ))}
        </div>
      </section>

      <section className="trk-card" aria-label="Bankroll history">
        <div className="trk-card-head">
          <h3>Bankroll over time</h3>
          <div className="trk-seg small" role="group" aria-label="Chart range">
            {RANGES.map(([label, n]) => (
              <button
                key={label}
                type="button"
                className={range === n ? "active" : ""}
                aria-pressed={range === n}
                onClick={() => setRange(n)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <LineChart
          label="Bankroll by day"
          days={days}
          series={[
            {
              label: "Bankroll",
              color: "#10b981",
              values: windowed.map((p) => p.bankroll),
            },
          ]}
        />
        <div className="trk-dd">
          <div>
            <span>MAX DRAWDOWN</span>
            <strong className={dd.maxCents > 0 ? "neg" : ""}>
              {dd.maxCents ? `-${money(dd.maxCents)}` : "$0.00"}
            </strong>
            <small>
              {dd.maxPct != null
                ? `${(dd.maxPct * 100).toFixed(1)}% of peak bankroll`
                : "of realized profit"}
              {dd.peakDay && dd.troughDay
                ? ` · ${dd.peakDay.slice(5)} → ${dd.troughDay.slice(5)}`
                : ""}
            </small>
          </div>
          <div>
            <span>CURRENT DRAWDOWN</span>
            <strong className={dd.currentCents > 0 ? "neg" : ""}>
              {dd.currentCents ? `-${money(dd.currentCents)}` : "At a high"}
            </strong>
            <small>below the best profit so far</small>
          </div>
        </div>
      </section>

      <section
        className="trk-card"
        aria-label="Expected versus realized profit"
      >
        <h3>Expected value vs. realized profit</h3>
        {evBets.length < 2 ? (
          <p className="trk-muted">
            Log two bets with an estimated edge to compare results.
          </p>
        ) : (
          <>
            <LineChart
              label="Expected value and realized profit on edge bets"
              days={days}
              series={[
                {
                  label: "Expected",
                  color: "#f59e0b",
                  dashed: true,
                  values: windowed.map(
                    (p) => p.evExpected - (base?.evExpected ?? 0),
                  ),
                },
                {
                  label: "Realized",
                  color: "#38bdf8",
                  values: windowed.map((p) => p.evPnl - (base?.evPnl ?? 0)),
                },
              ]}
            />
            <small className="trk-muted">
              {evBets.length} settled edge bets. Expected value is each
              bet&apos;s stake times the edge shown when you logged it. A gap is
              normal for small samples (variance); it closes slowly.
            </small>
          </>
        )}
      </section>

      <section className="trk-card" aria-label="Balances by sportsbook">
        <h3>Balances by sportsbook</h3>
        {rows.length === 0 ? (
          <p className="trk-empty">Add a deposit to start tracking balances.</p>
        ) : (
          <div className="trk-wrap">
            <table className="trk-table plain">
              <thead>
                <tr>
                  <th>Location</th>
                  <th className="trk-num">Available</th>
                  <th className="trk-num">In play</th>
                  <th className="trk-num">Total</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.book}>
                    <td>{bookLabel(r.book)}</td>
                    <td className={`trk-num ${r.liquid < 0 ? "neg" : ""}`}>
                      {money(r.liquid)}
                    </td>
                    <td className="trk-num">{money(r.pending)}</td>
                    <td className="trk-num">
                      <b>{money(r.liquid + r.pending)}</b>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="trk-card" aria-label="Add cash entry">
        <h3>Add a deposit, withdrawal or transfer</h3>
        <CashForm onSubmit={onAddCash} />
      </section>

      <section className="trk-card" aria-label="Ledger">
        <div className="trk-card-head">
          <h3>Ledger</h3>
          <a
            className="button secondary"
            href="/api/refresh/v1/tracker/export"
            download="corner-tracker.json"
          >
            Export backup
          </a>
        </div>
        {deleteError && (
          <div role="alert" className="arb-alert">
            <span>{deleteError}</span>
          </div>
        )}
        {entries.length === 0 ? (
          <p className="trk-empty">Nothing here yet.</p>
        ) : (
          <div className="trk-wrap">
            <table className="trk-table plain">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Type</th>
                  <th>Where</th>
                  <th className="trk-num">Amount</th>
                  <th className="trk-num">Net bankroll</th>
                  <th>Memo</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {entries.slice(0, shown).map((r) => (
                  <tr key={r.id}>
                    <td>{when(r.at)}</td>
                    <td>{KIND_LABEL[r.kind]}</td>
                    <td>
                      {r.toBook
                        ? `${bookLabel(r.book)} → ${bookLabel(r.toBook)}`
                        : bookLabel(r.book)}
                    </td>
                    <td
                      className={`trk-num ${r.amount > 0 ? "pos" : r.amount < 0 ? "neg" : ""}`}
                    >
                      {r.kind === "BOOK_TRANSFER"
                        ? money(r.amount)
                        : signedDollars(r.amount)}
                    </td>
                    <td className="trk-num">{money(r.running)}</td>
                    <td className="trk-memo">{r.memo}</td>
                    <td>
                      {r.cashId && (
                        <button
                          type="button"
                          className="link-button"
                          aria-label="Delete entry"
                          onClick={() => {
                            if (
                              !window.confirm(
                                "Delete this entry? Balances will be recalculated.",
                              )
                            )
                              return;
                            setDeleteError("");
                            onDeleteCash(r.cashId!).catch((e: unknown) =>
                              setDeleteError(
                                e instanceof Error
                                  ? e.message
                                  : "Could not delete.",
                              ),
                            );
                          }}
                        >
                          delete
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {entries.length > shown && (
          <button
            type="button"
            className="button secondary"
            onClick={() => setShown((n) => n + 100)}
          >
            Show more ({entries.length - shown} older)
          </button>
        )}
      </section>
    </div>
  );
}

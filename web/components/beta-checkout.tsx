"use client";
import { useEffect, useRef, useState } from "react";
import type { BetaOffer } from "./beta-membership";
import {
  canShowInstructions,
  paymentCall,
  type PaymentRequest,
} from "../lib/billing-api";

export function PaymentDetails({
  payment,
  now = Date.now(),
}: {
  payment: PaymentRequest;
  now?: number;
}) {
  if (payment.state === "approved")
    return (
      <p role="status">
        Payment approved. Sign in again to activate beta access and see your
        locked $50/month rate.
      </p>
    );
  if (payment.state === "submitted")
    return (
      <div role="status">
        <strong>Payment under review</strong>
        <p>
          Your transaction reference is saved. We will verify the received
          payment. Do not send another payment.
        </p>
      </div>
    );
  if (payment.state === "requested")
    return (
      <p role="status">
        Quote requested. We will prepare your exact crypto amount. Check back
        here before sending anything.
      </p>
    );
  if (payment.state === "cancelled")
    return (
      <p role="status">
        Request cancelled. No payment was initiated by this app.
      </p>
    );
  if (!canShowInstructions(payment, now))
    return (
      <p role="status">
        This quote is expired or unavailable. Do not send using an old quote. If
        you already sent funds, submit the transaction reference below or
        contact support.
      </p>
    );
  const details = payment.instructions!;
  return (
    <div className="beta-payment-details">
      <p>
        <strong>
          Send exactly {details.amount} {payment.asset}
        </strong>{" "}
        on <strong>{details.network}</strong>.
      </p>
      <p>
        Network fees are paid separately by you. The receiving wallet must
        receive the exact amount shown.
      </p>
      <label htmlFor="beta-address">Receiving address</label>
      <code
        id="beta-address"
        style={{
          display: "block",
          overflowWrap: "anywhere",
          whiteSpace: "normal",
        }}
      >
        {details.address}
      </code>
      {details.memo !== null ? (
        <p>
          <strong>Required memo / destination tag:</strong>{" "}
          <code style={{ overflowWrap: "anywhere" }}>{details.memo}</code>
        </p>
      ) : (
        <p>No memo or destination tag is required for this receiving wallet.</p>
      )}
      <p>
        Quote expires{" "}
        {new Date(details.expires_at * 1000).toLocaleString("en-US", {
          timeZone: "America/Chicago",
          dateStyle: "medium",
          timeStyle: "short",
        })}{" "}
        Central. Send only on the named network.
      </p>
    </div>
  );
}

export default function BetaCheckout({ offer }: { offer: BetaOffer }) {
  const [payment, setPayment] = useState<PaymentRequest | null>(null);
  const [asset, setAsset] = useState("XRP");
  const [accepted, setAccepted] = useState(false);
  const [reference, setReference] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState("");
  const [now, setNow] = useState(Date.now());
  const generation = useRef(0);
  const alive = useRef(true);
  const mutating = useRef(false);
  const paymentId = payment?.id;
  const state = payment?.state;

  useEffect(() => {
    alive.current = true;
    const controller = new AbortController();
    let pending = false;
    const refresh = async () => {
      if (pending || mutating.current || document.visibilityState === "hidden")
        return;
      pending = true;
      const version = generation.current;
      try {
        const current = await paymentCall(
          "/current",
          undefined,
          controller.signal,
        );
        if (!controller.signal.aborted && version === generation.current) {
          setPayment(current);
          setError("");
        }
      } catch (e) {
        if (!controller.signal.aborted && version === generation.current)
          setError(
            e instanceof Error ? e.message : "Payment details are unavailable.",
          );
      } finally {
        pending = false;
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    void refresh();
    const timer = setInterval(() => {
      void refresh();
    }, 30000);
    const visible = () => {
      void refresh();
    };
    document.addEventListener("visibilitychange", visible);
    return () => {
      alive.current = false;
      controller.abort();
      clearInterval(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  }, []);

  useEffect(() => {
    if (state !== "quoted") return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [state, paymentId]);

  async function act(path: string, body: unknown) {
    if (mutating.current) return;
    mutating.current = true;
    generation.current++;
    setBusy(true);
    setError("");
    setCopied("");
    try {
      const result = await paymentCall(path, body);
      if (alive.current) {
        setPayment(result);
        setNow(Date.now());
      }
    } catch (e) {
      if (alive.current)
        setError(
          e instanceof Error ? e.message : "Request failed. Please try again.",
        );
    } finally {
      mutating.current = false;
      if (alive.current) setBusy(false);
    }
  }
  async function copy(value: string, label: string) {
    try {
      await navigator.clipboard.writeText(value);
      if (alive.current) setCopied(`${label} copied.`);
    } catch {
      if (alive.current)
        setCopied("Copy was unavailable. Select and copy the value above.");
    }
  }
  if (!offer.payments_enabled || !offer.checkout_eligible) return null;
  const fresh =
    !payment || payment.state === "cancelled" || payment.state === "expired";
  return (
    <section
      className="trk-card account-card beta-checkout"
      aria-labelledby="beta-checkout-title"
    >
      <h3 id="beta-checkout-title">Continue beta - $50</h3>
      {loading ? (
        <p role="status">Loading your payment request...</p>
      ) : (
        <>
          {payment && (
            <PaymentDetails
              payment={
                error ? { ...payment, instructions: undefined } : payment
              }
              now={now}
            />
          )}
          {error && <p role="alert">{error}</p>}
          {!error && payment && canShowInstructions(payment, now) && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
              <button
                type="button"
                className="button secondary"
                onClick={() => copy(payment.instructions!.address, "Address")}
              >
                Copy address
              </button>
              <button
                type="button"
                className="button secondary"
                onClick={() => copy(payment.instructions!.amount, "Amount")}
              >
                Copy amount
              </button>
              {payment.instructions!.memo !== null && (
                <button
                  type="button"
                  className="button secondary"
                  onClick={() =>
                    copy(payment.instructions!.memo!, "Memo / tag")
                  }
                >
                  Copy memo / tag
                </button>
              )}
            </div>
          )}
          {copied && <p role="status">{copied}</p>}
          {payment && ["quoted", "expired"].includes(payment.state) && (
            <form
              className="account-form"
              onSubmit={(e) => {
                e.preventDefault();
                void act(`/${payment.id}/submit`, {
                  transaction_id: reference,
                });
              }}
            >
              <div className="field">
                <label htmlFor="beta-reference">
                  Already sent? Transaction reference
                </label>
                <input
                  id="beta-reference"
                  value={reference}
                  onChange={(e) => setReference(e.target.value)}
                  placeholder={
                    payment.asset === "HBAR"
                      ? "0.0.account@seconds.nanoseconds"
                      : "64-character transaction hash"
                  }
                  maxLength={160}
                  autoComplete="off"
                  spellCheck={false}
                  required
                />
              </div>
              <button className="button" disabled={busy || !reference.trim()}>
                Submit for review
              </button>
              <small>
                A reference does not confirm payment. We check the actual
                received transfer.
              </small>
            </form>
          )}
          {payment &&
            ["requested", "quoted", "expired"].includes(payment.state) && (
              <button
                className="button secondary"
                type="button"
                disabled={busy}
                onClick={() => void act(`/${payment.id}/cancel`, {})}
              >
                I have not sent funds - cancel request
              </button>
            )}
          {fresh && (
            <form
              className="account-form"
              onSubmit={(e) => {
                e.preventDefault();
                if (accepted)
                  void act("", { asset, terms_version: offer.terms_version });
              }}
            >
              <div className="field">
                <label htmlFor="beta-coin">Choose a coin</label>
                <select
                  id="beta-coin"
                  value={asset}
                  onChange={(e) => setAsset(e.target.value)}
                >
                  {offer.assets.map((coin) => (
                    <option key={coin}>{coin}</option>
                  ))}
                </select>
              </div>
              <label
                style={{
                  display: "flex",
                  gap: "0.5rem",
                  alignItems: "flex-start",
                }}
              >
                <input
                  type="checkbox"
                  checked={accepted}
                  onChange={(e) => setAccepted(e.target.checked)}
                  required
                />
                <span>
                  I accept the $50 one-time beta fee through November 20, 2026,
                  no refunds, and separately paid network fees. Paying locks in
                  $50/month for pregame standard markets after launch. There are
                  no automatic charges.
                </span>
              </label>
              <button
                className="button"
                disabled={busy || !accepted || Boolean(error)}
              >
                Request exact amount
              </button>
              <small>
                Do not send funds until your time-limited quote appears here.
              </small>
            </form>
          )}
          <p>
            <a href={`mailto:${offer.support_email}`}>Payment help</a>
          </p>
        </>
      )}
    </section>
  );
}

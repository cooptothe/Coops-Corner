"use client";

import { useEffect, useState } from "react";
import BetaCheckout from "./beta-checkout";
import { notifyUnauthorized } from "../lib/auth-api";

export interface BetaOffer {
  membership?: {
    state: string;
    expires_at: number | null;
    allowed: boolean;
    enforced: boolean;
  } | null;
  private_beta: boolean;
  stage: "preparation" | "manual_review";
  payments_enabled: boolean;
  checkout_eligible?: boolean;
  terms_version: string;
  trial_days: number;
  price_usd_cents: number;
  standard_monthly_usd_cents?: number;
  founder_monthly_usd_cents?: number;
  package_label?: string;
  founder?: boolean;
  access_end_label: string;
  assets: string[];
  support_email: string;
}

export function MembershipOffer({ offer }: { offer: BetaOffer }) {
  if (!offer.private_beta) return null;
  return (
    <section
      className="trk-card account-card"
      aria-labelledby="beta-membership-title"
    >
      <h3 id="beta-membership-title">Your beta membership</h3>
      <p>
        <strong>{offer.trial_days} days free.</strong> Then choose whether to
        continue for a one-time{" "}
        <strong>${(offer.price_usd_cents / 100).toFixed(0)}</strong>.
      </p>
      <p className="trk-muted">
        Paid beta access runs through {offer.access_end_label}. No refunds. No
        automatic charges or renewal.
      </p>
      <p>
        If you skip the $50 beta option, you can subscribe when the app launches
        at the standard ${(offer.standard_monthly_usd_cents ?? 12500) / 100}
        /month. Your free trial will not automatically become a paid
        subscription.
      </p>
      <p>
        {offer.founder
          ? "Your locked-in rate is"
          : "Paying the $50 beta fee locks in"}{" "}
        <strong>
          ${(offer.founder_monthly_usd_cents ?? 5000) / 100}/month
        </strong>{" "}
        for the {offer.package_label ?? "Pregame standard markets"} package
        after launch. No automatic enrollment or recurring charge.
      </p>
      <p>Pay with {offer.assets.join(", ")}.</p>
      <p role="status">
        {!offer.payments_enabled && "Payments are not open yet. "}
        {!offer.membership?.enforced
          ? "Your current preview access is unchanged."
          : offer.membership.state === "operator"
            ? "You have operator access."
            : offer.membership.state === "not_started"
              ? "Your trial has not started. Contact support to begin."
              : offer.membership.state === "expired"
                ? "Your membership access has ended. Account and your personal tracker remain available."
                : offer.membership.expires_at
                  ? `Your ${offer.membership.state === "paid" ? "paid access" : "trial"} ends ${new Date(offer.membership.expires_at * 1000).toLocaleString("en-US", { timeZone: "America/Chicago", dateStyle: "medium", timeStyle: "short" })} Central.`
                  : "Contact support about your membership."}
      </p>
      <p>
        <a href={`mailto:${offer.support_email}`}>Contact support</a>
      </p>
    </section>
  );
}

export default function BetaMembership() {
  const [offer, setOffer] = useState<BetaOffer | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setFailed(false);
    fetch("/api/refresh/v1/billing/status", {
      cache: "no-store",
      signal: AbortSignal.any([controller.signal, AbortSignal.timeout(20000)]),
    })
      .then(async (response) => {
        if (response.status === 401) notifyUnauthorized();
        if (!response.ok) throw new Error("Membership details unavailable");
        const data: BetaOffer = await response.json();
        if (!controller.signal.aborted) setOffer(data);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, [attempt]);
  if (failed)
    return (
      <section className="trk-card account-card">
        <p role="alert">
          Membership details are temporarily unavailable. Please try again
          later.
        </p>
        <button
          type="button"
          className="button secondary"
          onClick={() => setAttempt((n) => n + 1)}
        >
          Try again
        </button>
      </section>
    );
  return offer ? (
    <>
      <MembershipOffer offer={offer} />
      {offer.private_beta &&
        offer.payments_enabled &&
        offer.checkout_eligible && <BetaCheckout offer={offer} />}
    </>
  ) : (
    <p role="status">Loading membership details…</p>
  );
}

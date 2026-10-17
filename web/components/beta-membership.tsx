"use client";

import { useEffect, useState } from "react";
import { notifyUnauthorized } from "../lib/auth-api";

export interface BetaOffer {
  private_beta: boolean;
  stage: "preparation";
  payments_enabled: false;
  terms_version: string;
  trial_days: number;
  price_usd_cents: number;
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
      <p>Pay with {offer.assets.join(", ")}.</p>
      <p role="status">
        Payments are not open yet. Your current preview access is unchanged.
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
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/refresh/v1/billing/status", {
      cache: "no-store",
      signal: controller.signal,
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
  }, []);
  if (failed)
    return (
      <section className="trk-card account-card">
        <p role="alert">
          Membership details are temporarily unavailable. Please try again
          later.
        </p>
      </section>
    );
  return offer ? <MembershipOffer offer={offer} /> : null;
}

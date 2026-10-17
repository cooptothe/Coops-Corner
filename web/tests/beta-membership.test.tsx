import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { MembershipOffer, type BetaOffer } from "../components/beta-membership";

const offer: BetaOffer = {
  private_beta: true,
  stage: "preparation",
  payments_enabled: false,
  terms_version: "beta-2026-11-20-two-day-v1",
  trial_days: 2,
  price_usd_cents: 5000,
  access_end_label: "November 20, 2026, at 11:59 p.m. Central",
  assets: ["XRP", "HBAR", "XLM"],
  support_email: "admin@coopscorner.tech",
};

test("membership offer shows the confirmed simple terms and support", () => {
  const html = renderToStaticMarkup(<MembershipOffer offer={offer} />);
  assert.match(html, /2 days free/);
  assert.match(html, /\$50/);
  assert.match(html, /November 20, 2026/);
  assert.match(html, /No refunds/);
  assert.match(html, /No automatic charges or renewal/);
  assert.match(html, /XRP, HBAR, XLM/);
  assert.match(html, /mailto:admin@coopscorner.tech/);
  assert.doesNotMatch(html, /ONDO|<button|wallet address/i);
});

test("local accounts do not acquire a beta offer", () => {
  assert.equal(
    renderToStaticMarkup(
      <MembershipOffer offer={{ ...offer, private_beta: false }} />,
    ),
    "",
  );
});

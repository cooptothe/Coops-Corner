import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { PaymentDetails } from "../components/beta-checkout";
import { canShowInstructions, type PaymentRequest } from "../lib/billing-api";
const payment: PaymentRequest = {
  id: "fixture",
  asset: "XRP",
  state: "quoted",
  expires_at: 2000,
  terms_version: "fixture",
  transaction_id: null,
  instructions: {
    address: "fixture-receiving-address",
    memo: "42",
    amount: "25.000000",
    network: "xrpl-mainnet",
    expires_at: 2000,
  },
};

test("payment instructions show exact native amount, network, memo and fee responsibility", () => {
  const html = renderToStaticMarkup(
    <PaymentDetails payment={payment} now={1999999} />,
  );
  for (const value of [
    "25.000000 XRP",
    "xrpl-mainnet",
    "fixture-receiving-address",
    "42",
    "Network fees",
    "Central",
  ])
    assert.ok(html.includes(value));
});
test("expired, missing or nonpayable quotes never show receiving instructions", () => {
  assert.equal(canShowInstructions(payment, 2000000), false);
  for (const value of [
    { ...payment, state: "expired" as const },
    { ...payment, instructions: undefined },
    payment,
  ]) {
    const html = renderToStaticMarkup(
      <PaymentDetails payment={value} now={2000000} />,
    );
    assert.doesNotMatch(html, /fixture-receiving-address|25[.]000000/);
    assert.match(html, /Do not send/);
  }
});
test("submitted references are pending review and approved status asks for fresh login", () => {
  const html = renderToStaticMarkup(
    <PaymentDetails payment={{ ...payment, state: "submitted" }} />,
  );
  assert.match(html, /Payment under review/);
  assert.match(html, /Do not send another/);
  assert.doesNotMatch(html, /fixture-receiving-address/);
  const approved = renderToStaticMarkup(
    <PaymentDetails payment={{ ...payment, state: "approved" }} />,
  );
  assert.match(approved, /Sign in again/);
  assert.match(approved, /locked \$50/);
});

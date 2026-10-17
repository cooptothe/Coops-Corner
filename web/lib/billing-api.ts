import { notifyUnauthorized } from "./auth-api";

export interface PaymentRequest {
  id: string;
  asset: string;
  state:
    "requested" | "quoted" | "submitted" | "expired" | "cancelled" | "approved";
  expires_at: number | null;
  terms_version: string;
  transaction_id: string | null;
  instructions?: {
    address: string;
    memo: string | null;
    amount: string;
    network: string;
    expires_at: number;
  };
}

export function canShowInstructions(
  payment: PaymentRequest,
  now = Date.now(),
): boolean {
  return (
    payment.state === "quoted" &&
    Boolean(payment.instructions) &&
    payment.expires_at !== null &&
    now < payment.expires_at * 1000 &&
    now < payment.instructions!.expires_at * 1000
  );
}

export async function paymentCall(
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<PaymentRequest | null> {
  const response = await fetch(`/api/refresh/v1/billing/requests${path}`, {
    method: body === undefined ? "GET" : "POST",
    cache: "no-store",
    credentials: "same-origin",
    ...(body === undefined
      ? {}
      : {
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }),
    signal: AbortSignal.any([
      ...(signal ? [signal] : []),
      AbortSignal.timeout(20000),
    ]),
  });
  if (response.status === 401) notifyUnauthorized();
  const data = await response.json().catch(() => null);
  if (!response.ok)
    throw new Error(
      typeof data?.error === "string"
        ? data.error
        : "Payment details are unavailable. Please try again.",
    );
  return data.payment ?? null;
}

export type InvitationOffer = {
  cohort: "beta" | "friend" | "family";
  paid: boolean;
  claimed: boolean;
  version: string;
  terms_version: string;
  expires_at: number;
  username: string;
  trial_available: boolean;
  title: string;
  access: string;
  pricing: string;
  end_label: string;
};
export function invitationToken(hash: string): string {
  const raw = hash.replace(/^#/, "");
  const value = raw.startsWith("invite=") ? raw.slice(7) : raw;
  return /^[A-Za-z0-9_-]{20,200}$/.test(value) ? value : "";
}
export async function invitationRequest<T>(
  operation: string,
  body: object,
): Promise<T> {
  const response = await fetch(`/api/refresh/v1/invitations/${operation}`, {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok)
    throw new Error(result.error || "Please try again shortly.");
  return result;
}

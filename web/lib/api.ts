import type { Envelope, Page } from "./contracts.ts";

export class ApiError extends Error {
  code: string;
  status: number;
  constructor(message: string, code = "request_failed", status = 0) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}
export function validateEnvelope<T>(
  value: unknown,
  snapshot?: string,
): Envelope<T> {
  if (!value || typeof value !== "object")
    throw new ApiError("Invalid API response.", "invalid_response");
  const body = value as Partial<Envelope<T>>;
  if (
    body.meta?.format !== "corner.product_api/1" ||
    !["fixture", "database"].includes(body.meta.data_mode as string) ||
    body.meta.production_authorized !== false ||
    body.meta.availability_verified !== false ||
    typeof body.meta.snapshot_id !== "string"
  )
    throw new ApiError("Unsupported API environment.", "unsupported_response");
  if (snapshot && snapshot !== body.meta.snapshot_id)
    throw new ApiError(
      "Snapshot changed. Reload the workspace.",
      "snapshot_changed",
      409,
    );
  if (!Object.hasOwn(body, "data"))
    throw new ApiError("Response is missing data.", "invalid_response");
  return body as Envelope<T>;
}
export async function request<T>(
  path: string,
  options: {
    params?: Record<string, string | number | boolean | undefined>;
    body?: unknown;
    signal?: AbortSignal;
    snapshot?: string;
    fetcher?: typeof fetch;
  } = {},
): Promise<Envelope<T>> {
  const controller = new AbortController();
  let timedOut = false;
  const abort = () => controller.abort();
  options.signal?.addEventListener("abort", abort, { once: true });
  if (options.signal?.aborted) abort();
  const timer = setTimeout(() => {
    timedOut = true;
    abort();
  }, 45000);
  const query = new URLSearchParams(
    Object.entries(options.params ?? {})
      .filter(([, v]) => v !== undefined && v !== "")
      .map(([k, v]) => [k, String(v)]),
  );
  try {
    if (controller.signal.aborted)
      throw new DOMException("Request cancelled", "AbortError");
    const response = await (options.fetcher ?? fetch)(
      `/api/v1/${path}${query.size ? "?" + query : ""}`,
      {
        method: options.body ? "POST" : "GET",
        cache: "no-store",
        signal: controller.signal,
        ...(options.body
          ? {
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(options.body),
            }
          : {}),
      },
    );
    const body: unknown = await response.json().catch(() => {
      throw new ApiError("API did not return JSON.", "invalid_response");
    });
    if (controller.signal.aborted)
      throw new DOMException("Request cancelled", "AbortError");
    if (!response.ok) {
      const error = (body as { error?: { message?: string; code?: string } })
        ?.error;
      throw new ApiError(
        error?.message ?? `Request failed (${response.status})`,
        error?.code,
        response.status,
      );
    }
    return validateEnvelope<T>(body, options.snapshot);
  } catch (error) {
    if (options.signal?.aborted)
      throw new DOMException("Request cancelled", "AbortError");
    if (timedOut) throw new ApiError("API response timed out.", "timeout");
    if (error instanceof ApiError) throw error;
    throw new ApiError("Cannot reach the local tools API.", "offline");
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener("abort", abort);
  }
}
export async function allPages<T>(
  path: string,
  snapshot: string,
  signal: AbortSignal,
): Promise<T[]> {
  const items: T[] = [];
  let offset = 0;
  for (let n = 0; n < 101; n++) {
    const { data } = await request<Page<T>>(path, {
      params: { limit: 100, offset, snapshot_id: snapshot },
      snapshot,
      signal,
    });
    if (
      !Array.isArray(data.items) ||
      data.offset !== offset ||
      data.items.length > 100
    )
      throw new ApiError("Invalid page.", "invalid_response");
    items.push(...data.items);
    if (data.next_offset === null) return items;
    if (
      !Number.isInteger(data.next_offset) ||
      data.next_offset <= offset ||
      data.next_offset > 10000
    )
      throw new ApiError("Invalid page cursor.", "invalid_response");
    offset = data.next_offset;
  }
  throw new ApiError("Snapshot exceeds the client page bound.", "page_limit");
}

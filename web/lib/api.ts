import { notifyUnauthorized } from "./auth-api.ts";
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
    if (response.status === 401) notifyUnauthorized();
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
const PAGE_LIMIT = 100;
const FAN_OUT = 6; // the browser's connections per host; more only queues

interface PageOptions {
  limit?: number;
  maxOffset?: number;
}

async function inParallel<I, O>(
  inputs: I[],
  width: number,
  work: (input: I) => Promise<O>,
): Promise<O[]> {
  const out: O[] = new Array(inputs.length);
  let next = 0;
  let failed = false;
  const lane = async () => {
    while (!failed && next < inputs.length) {
      const at = next++;
      try {
        out[at] = await work(inputs[at]);
      } catch (error) {
        failed = true;
        throw error;
      }
    }
  };
  await Promise.all(
    Array.from({ length: Math.min(width, inputs.length) }, lane),
  );
  return out;
}

// Every page of a list. Once the first page reports a total and a regular cursor, the other pages are
// requested side by side; otherwise (or against a server that does not) the cursors are followed one by one.
export async function allPages<T>(
  path: string,
  snapshot: string,
  signal: AbortSignal,
  { limit = PAGE_LIMIT, maxOffset = 10000 }: PageOptions = {},
): Promise<T[]> {
  const get = async (offset: number) => {
    const { data } = await request<Page<T>>(path, {
      params: { limit, offset, snapshot_id: snapshot },
      snapshot,
      signal,
    });
    if (
      !Array.isArray(data.items) ||
      data.offset !== offset ||
      data.items.length > limit
    )
      throw new ApiError("Invalid page.", "invalid_response");
    return data;
  };
  const first = await get(0);
  if (first.next_offset === null) return first.items;
  if (
    Number.isInteger(first.total) &&
    first.next_offset === limit &&
    first.total > limit
  ) {
    const offsets: number[] = [];
    for (let at = limit; at < first.total; at += limit) offsets.push(at);
    if (offsets[offsets.length - 1] > maxOffset)
      throw new ApiError(
        "Snapshot exceeds the client page bound.",
        "page_limit",
      );
    const rest = await inParallel(offsets, FAN_OUT, get);
    const items = [first, ...rest].flatMap((page, n) => {
      if (
        page.total !== first.total ||
        (n < rest.length && page.items.length !== limit)
      )
        throw new ApiError("Invalid page.", "invalid_response");
      return page.items;
    });
    if (items.length !== first.total)
      throw new ApiError("Invalid page.", "invalid_response");
    return items;
  }
  const items: T[] = [...first.items];
  let offset = 0;
  let data = first;
  for (let n = 1; n < 101; n++) {
    if (
      !Number.isInteger(data.next_offset) ||
      data.next_offset === null ||
      data.next_offset <= offset ||
      data.next_offset > maxOffset
    )
      throw new ApiError("Invalid page cursor.", "invalid_response");
    offset = data.next_offset;
    data = await get(offset);
    items.push(...data.items);
    if (data.next_offset === null) return items;
  }
  throw new ApiError("Snapshot exceeds the client page bound.", "page_limit");
}

// The same list for the same snapshot is the same data, so it is fetched once however many parts of the page ask,
// and a caller can start it early. A caller leaving does not cancel the shared request; a failed one is forgotten.
const shared = new Map<string, Promise<unknown[]>>();
const SHARED_MAX = 8;
export function sharedPages<T>(
  path: string,
  snapshot: string,
  signal: AbortSignal,
  options: PageOptions = {},
): Promise<T[]> {
  const key = `${snapshot}|${path}|${options.limit ?? PAGE_LIMIT}`;
  let pending = shared.get(key);
  if (!pending) {
    pending = allPages<T>(
      path,
      snapshot,
      new AbortController().signal,
      options,
    );
    shared.set(key, pending);
    pending.catch(() => {
      if (shared.get(key) === pending) shared.delete(key);
    });
    while (shared.size > SHARED_MAX) shared.delete(shared.keys().next().value!);
  }
  const wait = pending as Promise<T[]>;
  return new Promise<T[]>((resolve, reject) => {
    const cancel = () =>
      reject(new DOMException("Request cancelled", "AbortError"));
    if (signal.aborted) return cancel();
    signal.addEventListener("abort", cancel, { once: true });
    wait.then(
      (items) => {
        signal.removeEventListener("abort", cancel);
        resolve(items.slice());
      },
      (error) => {
        signal.removeEventListener("abort", cancel);
        reject(error);
      },
    );
  });
}

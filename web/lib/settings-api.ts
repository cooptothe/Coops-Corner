import { notifyUnauthorized } from "./auth-api";

export type Settings = Record<string, unknown>;
export interface Preset {
  id: string;
  name: string;
  settings: Settings;
}
export interface SettingsData {
  tools: Record<string, Settings>;
  presets: Record<string, Preset[]>;
}

export class SettingsRequestError extends Error {}

const BASE = "/api/refresh/v1/settings";

async function call<T>(
  method: "GET" | "PUT" | "POST" | "DELETE",
  path: string,
  body?: unknown,
  keepalive = false,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      method,
      cache: "no-store",
      keepalive,
      ...(body !== undefined && {
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
      signal: AbortSignal.timeout(15000),
    });
  } catch {
    throw new SettingsRequestError("Could not reach the server.");
  }
  const data = await response.json().catch(() => null);
  if (response.status === 401) notifyUnauthorized();
  if (!response.ok)
    throw new SettingsRequestError(
      (data && typeof data.error === "string" && data.error) ||
        "The settings could not be saved.",
    );
  return data as T;
}

export const loadSettings = () => call<SettingsData>("GET", "");
export const saveToolSettings = (
  tool: string,
  settings: Settings,
  keepalive = false,
) => call<unknown>("PUT", `/${tool}`, { settings }, keepalive);
export const savePresetRequest = (
  tool: string,
  name: string,
  settings: Settings,
) =>
  call<{ preset: Preset }>("POST", `/${tool}/presets`, { name, settings }).then(
    (r) => r.preset,
  );
export const deletePresetRequest = (id: string) =>
  call<unknown>("DELETE", `/presets/${id}`);

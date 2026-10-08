// Small validators for reading saved settings back. Saved values come from storage, so every page checks each one
// and falls back to its default instead of trusting it.
export const text = (value: unknown, pattern: RegExp, fallback: string) =>
  typeof value === "string" && pattern.test(value) ? value : fallback;

export const list = (value: unknown): string[] =>
  Array.isArray(value)
    ? value
        .filter((v) => typeof v === "string" || typeof v === "number")
        .map(String)
        .slice(0, 300)
    : [];

export function choice<K extends string>(
  value: unknown,
  allowed: readonly K[] | Record<K, unknown>,
  fallback: K,
): K {
  const keys: readonly string[] = Array.isArray(allowed)
    ? allowed
    : Object.keys(allowed);
  return typeof value === "string" && keys.includes(value)
    ? (value as K)
    : fallback;
}

export const sorted = (values: Iterable<string>) => [...values].sort();

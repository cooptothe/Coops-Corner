import type { PropBet, PropsStatus, PropMarketInfo } from "./refresh-api";

// Provider/backend Decimal strings sometimes use exponent notation, including
// exact zero (0E-28). Expand digits without a floating-point round trip.
export function propDecimal(value: unknown): string {
  if (typeof value !== "string" || value.length > 120)
    throw Error("Invalid prop decimal");
  const m = /^(-?)(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d{1,3}))?$/.exec(value);
  if (!m) throw Error("Invalid prop decimal");
  let digits = (m[2] + (m[3] ?? "")).replace(/^0+/, "") || "0";
  let scale = (m[3]?.length ?? 0) - Number(m[4] ?? 0);
  if (Math.abs(scale) > 100 || digits.length + Math.max(0, -scale) > 120)
    throw Error("Prop decimal is too large");
  if (scale < 0) {
    digits += "0".repeat(-scale);
    scale = 0;
  }
  digits = digits.padStart(scale + 1, "0");
  let text = scale
    ? digits.slice(0, -scale) + "." + digits.slice(-scale)
    : digits;
  if (text.includes(".")) text = text.replace(/0+$/, "").replace(/\.$/, "");
  const result = (m[1] && /[1-9]/.test(text) ? "-" : "") + text;
  if (result.length > 120) throw Error("Prop decimal is too large");
  return result;
}
const record = (x: unknown): x is Record<string, unknown> =>
  Boolean(x) && typeof x === "object" && !Array.isArray(x);
const strings = (x: unknown): x is string[] =>
  Array.isArray(x) && x.every((v) => typeof v === "string");
function bet(value: unknown): PropBet | null {
  if (!record(value)) return null;
  const b = { ...value };
  try {
    for (const key of [
      "id",
      "event_id",
      "sport_key",
      "home",
      "away",
      "starts_at",
      "market_key",
      "market_label",
      "group",
      "player",
      "side",
      "book",
    ])
      if (typeof b[key] !== "string" || !(b[key] as string).trim()) return null;
    if (
      !Number.isFinite(Date.parse(b.starts_at as string)) ||
      !strings(b.sharps)
    )
      return null;
    for (const key of ["price", "ev", "fair_probability"])
      b[key] = propDecimal(b[key]);
    if (
      Number(b.price) <= 1 ||
      Number(b.price) > 1000000 ||
      !Number.isFinite(Number(b.ev)) ||
      Number(b.fair_probability) < 0 ||
      Number(b.fair_probability) > 1
    )
      return null;
    b.point = b.point == null ? null : propDecimal(b.point);
    for (const key of [
      "net_decimal_odds",
      "commission_rate",
      "assumed_margin",
      "stress_margin",
      "market_width_cents",
    ])
      if (b[key] != null) b[key] = propDecimal(b[key]);
    if (
      b.observed_at != null &&
      (typeof b.observed_at !== "string" ||
        !Number.isFinite(Date.parse(b.observed_at)))
    )
      return null;
    b.observed_at ??= null;
    if (b.devig_comparisons != null) {
      if (!Array.isArray(b.devig_comparisons)) return null;
      b.devig_comparisons = b.devig_comparisons.flatMap((row) => {
        if (!record(row) || typeof row.method !== "string") return [];
        try {
          const probability = propDecimal(row.probability),
            ev = propDecimal(row.ev);
          return Number(probability) >= 0 &&
            Number(probability) <= 1 &&
            Number.isFinite(Number(ev))
            ? [{ method: row.method, probability, ev }]
            : [];
        } catch {
          return [];
        }
      });
    }
    if (b.allocation_sensitivity != null) {
      if (!record(b.allocation_sensitivity)) return null;
      b.allocation_sensitivity = { ...b.allocation_sensitivity };
      for (const key of [
        "probability_min",
        "probability_max",
        "ev_min",
        "ev_max",
      ])
        (b.allocation_sensitivity as Record<string, unknown>)[key] =
          propDecimal(
            (b.allocation_sensitivity as Record<string, unknown>)[key],
          );
    }
    for (const key of ["dfs_assumption", "probability_basis"])
      if (b[key] != null && typeof b[key] !== "string") return null;
    if (b.reference_weights != null && !record(b.reference_weights))
      return null;
    return b as unknown as PropBet;
  } catch {
    return null;
  }
}

export function parsePropsStatus(value: unknown): PropsStatus {
  if (
    !record(value) ||
    (!Object.hasOwn(value, "bets") && !Array.isArray(value.sports)) ||
    typeof value.error === "string"
  )
    throw Error(
      "The props service returned an invalid response. Please try again.",
    );
  if (value.bets != null && !Array.isArray(value.bets))
    throw Error("The props list was invalid. Please try again.");
  const raw = (value.bets ?? []) as unknown[];
  const seen = new Set<string>();
  const bets = raw.flatMap((row) => {
    const b = bet(row);
    if (!b || seen.has(b.id)) return [];
    seen.add(b.id);
    return [b];
  });
  const sports = Array.isArray(value.sports)
    ? value.sports.filter(
        (s): s is { key: string; label: string } =>
          record(s) && typeof s.key === "string" && typeof s.label === "string",
      )
    : [];
  const markets: Record<string, PropMarketInfo[]> = {};
  if (record(value.markets))
    for (const [sport, list] of Object.entries(value.markets)) {
      if (Array.isArray(list))
        markets[sport] = list.filter(
          (m): m is PropMarketInfo =>
            record(m) &&
            typeof m.key === "string" &&
            typeof m.label === "string" &&
            typeof m.group === "string" &&
            (m.kind === "two_way" || m.kind === "yes_only") &&
            typeof m.default === "boolean",
        );
    }
  const positive = (x: unknown, fallback: number) =>
    typeof x === "number" && Number.isFinite(x) && x > 0 ? x : fallback;
  return {
    ...value,
    sports,
    markets,
    bets,
    invalid_bets: raw.length - bets.length,
    manual_fetch_enabled:
      value.manual_fetch_enabled === true && sports.length > 0,
    default_events: positive(value.default_events, 8),
    max_events: positive(value.max_events, 20),
    max_age_seconds: positive(value.max_age_seconds, 1800),
    last_success_at:
      typeof value.last_success_at === "string" &&
      Number.isFinite(Date.parse(value.last_success_at))
        ? value.last_success_at
        : null,
  } as PropsStatus;
}

export function quoteAgeStatus(value: string | null, now: number) {
  const timestamp = value ? Date.parse(value) : NaN;
  if (!now || !Number.isFinite(timestamp) || timestamp > now + 5000)
    return "unknown";
  const age = now - timestamp;
  return age >= 30 * 60 * 1000
    ? "expired"
    : age >= 5 * 60 * 1000
      ? "review"
      : "recent";
}

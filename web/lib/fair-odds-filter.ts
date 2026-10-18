// Exact fair-price filtering. Bounds are American odds; probabilities are never changed.
type Ratio = { n: bigint; d: bigint };
function bound(text: string): Ratio | null | false {
  if (!text.trim()) return null;
  if (!/^[+-]?\d{2,5}$/.test(text.trim())) return false;
  const value = BigInt(text);
  const magnitude = value < 0n ? -value : value;
  if (magnitude < 100n) return false;
  return { n: magnitude + 100n, d: value < 0n ? magnitude : 100n };
}
export function fairOddsRange(minimum: string, maximum: string) {
  const min = bound(minimum),
    max = bound(maximum);
  const valid =
    min !== false &&
    max !== false &&
    !(min && max && min.n * max.d > max.n * min.d);
  return {
    valid,
    test(probability: string | null | undefined): boolean {
      if (!valid) return false;
      if (!min && !max) return true;
      if (
        !probability ||
        probability.length > 100 ||
        !/^(0|1)(\.\d+)?$/.test(probability)
      )
        return false;
      const [whole, frac = ""] = probability.split(".");
      const n = BigInt(whole + frac),
        d = 10n ** BigInt(frac.length);
      if (n <= 0n || n > d) return false;
      return (
        (!min || d * min.d >= min.n * n) && (!max || d * max.d <= max.n * n)
      );
    },
  };
}

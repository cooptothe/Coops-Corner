import { compareDecimal, shiftDecimal } from "../../frontend/format.mjs";

export const LIMIT_PATTERN = /^\d{1,6}(\.\d{1,2})?$/;

// Continuous American-odds cents around even money: -110 => -10, +120 => 20.
export function marketWidth(prices: string[]): number | null {
  if (prices.length !== 2) return null;
  const decimals = prices.map(Number);
  if (decimals.some((d) => !Number.isFinite(d) || d <= 1)) return null;
  const cents = decimals.map((d) =>
    d >= 2 ? 100 * (d - 2) : 100 - 100 / (d - 1),
  );
  return Math.round(Math.abs(cents[0] + cents[1]) * 1e6) / 1e6;
}

export function widestMarket(groups: string[][]): number | null {
  if (!groups.length) return null;
  const widths = groups.map(marketWidth);
  return widths.some((w) => w === null)
    ? null
    : Math.max(...(widths as number[]));
}

export function matchesEvLimits(
  ev: string,
  width: number | null,
  maxEv: string,
  maxWidth: string,
) {
  return (
    (!maxEv ||
      (LIMIT_PATTERN.test(maxEv) &&
        compareDecimal(ev, shiftDecimal(maxEv, -2)) <= 0)) &&
    (!maxWidth ||
      (LIMIT_PATTERN.test(maxWidth) &&
        width !== null &&
        Number.isFinite(width) &&
        width <= Number(maxWidth)))
  );
}

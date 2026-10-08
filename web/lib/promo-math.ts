export type PromoType = "bonus" | "credit" | "nosweat";

export interface Conversion {
  hedge: number;
  // Cash out of pocket across both legs: the hedge, plus the cash bet that triggers a risk-free bet.
  capital: number;
  ifPromoWins: number;
  ifHedgeWins: number;
  // Assumed cash value of the refund voucher, which only arrives after it is converted (risk-free bets only).
  voucherValue: number;
  profit: number;
  rate: number;
}

// d1 is the promo leg's decimal odds, d2 the cash hedge's. face is the promo
// value (or the cash stake that triggers a no-sweat bet) and r is the assumed
// value of the refund voucher as a share of its face value.
export function convert(
  type: PromoType,
  face: number,
  d1: number,
  d2: number,
  r = 0.75,
): Conversion | null {
  if (!(face > 0) || !(d1 > 1) || !(d2 > 1)) return null;
  const hedge =
    type === "bonus"
      ? Math.round(((face * (d1 - 1)) / d2) * 100) / 100
      : type === "credit"
        ? Math.round(((face * d1) / d2) * 100) / 100
        : Math.round(((face * (d1 - r)) / d2) * 100) / 100;
  // Net cash after both outcomes, counting only money actually out of pocket.
  const ifPromoWins =
    type === "bonus"
      ? face * (d1 - 1) - hedge
      : type === "credit"
        ? face * d1 - hedge
        : face * (d1 - 1) - hedge;
  const ifHedgeWins =
    type === "nosweat" ? -face + r * face + hedge * (d2 - 1) : hedge * (d2 - 1);
  const profit = Math.min(ifPromoWins, ifHedgeWins);
  const capital = type === "nosweat" ? face + hedge : hedge;
  const voucherValue = type === "nosweat" ? r * face : 0;
  return {
    hedge,
    capital,
    ifPromoWins,
    ifHedgeWins,
    voucherValue,
    profit,
    rate: profit / face,
  };
}

export const toDecimal = (american: number) =>
  american > 0 ? 1 + american / 100 : 1 + 100 / -american;

export const toAmerican = (decimal: number) =>
  decimal >= 2 ? (decimal - 1) * 100 : -100 / (decimal - 1);

// Distance of an American price from even money, signed so that a pair of opposing
// prices sums to the book's margin in cents: +200 is -100, -220 is +120, so +200/-220 is 20c wide.
const centsFromEven = (decimal: number) => {
  const a = toAmerican(decimal);
  return a > 0 ? 100 - a : -a - 100;
};
export const WIDE_MARKET_CENTS = 30;
export const marketWidthCents = (d1: number, d2: number) =>
  Math.max(0, Math.round(centsFromEven(d1) + centsFromEven(d2)));

export type EfficiencyTier = "low" | "mid" | "good" | "elite";
// Red below 65%, amber 65-75%, lime 75-80% (between the two named bands), emerald from 80%.
export const efficiencyTier = (rate: number): EfficiencyTier =>
  rate >= 0.8 ? "elite" : rate >= 0.75 ? "good" : rate >= 0.65 ? "mid" : "low";

export const parseAmerican = (text: string): number | null => {
  if (!/^[+-]?\d{3,5}$/.test(text.trim())) return null;
  const n = Number(text);
  return Math.abs(n) >= 100 ? n : null;
};

export type PromoType = "bonus" | "credit" | "nosweat";

export interface Conversion {
  hedge: number;
  ifPromoWins: number;
  ifHedgeWins: number;
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
  return { hedge, ifPromoWins, ifHedgeWins, profit, rate: profit / face };
}

export const toDecimal = (american: number) =>
  american > 0 ? 1 + american / 100 : 1 + 100 / -american;

export const parseAmerican = (text: string): number | null => {
  if (!/^[+-]?\d{3,5}$/.test(text.trim())) return null;
  const n = Number(text);
  return Math.abs(n) >= 100 ? n : null;
};

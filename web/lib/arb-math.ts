export type ArbMode = "symmetric" | "biased";

export interface ArbSizing {
  stakes: number[];
  returns: number[];
  totalImplied: number;
  totalStake: number;
  guaranteedReturn: number;
  netProfit: number;
  bestProfit: number;
}

const cents = (n: number) => Math.round(n * 100) / 100;
const valid = (odds: number[]) =>
  odds.length >= 2 &&
  odds.every((o) => Number.isFinite(o) && o > 1) &&
  totalImplied(odds) < 1;

export const impliedProbability = (decimalOdds: number) => 1 / decimalOdds;
export const totalImplied = (odds: number[]) =>
  odds.reduce((sum, o) => sum + impliedProbability(o), 0);
export const profitPercent = (odds: number[]) => 1 / totalImplied(odds) - 1;

function summarize(stakes: number[], odds: number[], total: number): ArbSizing {
  const returns = stakes.map((s, i) => cents(s * odds[i]));
  const guaranteedReturn = Math.min(...returns);
  return {
    stakes,
    returns,
    totalImplied: totalImplied(odds),
    totalStake: total,
    guaranteedReturn,
    netProfit: cents(guaranteedReturn - total),
    bestProfit: cents(Math.max(...returns) - total),
  };
}

// Stake_i = total * p_i / sum(p); the last leg takes the cent remainder.
export function symmetricStakes(
  total: number,
  odds: number[],
): ArbSizing | null {
  if (!valid(odds) || !(total > 0)) return null;
  const sum = totalImplied(odds);
  const stakes = odds.map((o) => cents((total * impliedProbability(o)) / sum));
  stakes[stakes.length - 1] = cents(
    total - stakes.slice(0, -1).reduce((a, b) => a + b, 0),
  );
  return summarize(stakes, odds, total);
}

// Every other leg only returns the total stake; the rest rides on the favored leg.
export function biasedStakes(
  total: number,
  odds: number[],
  favored: number,
): ArbSizing | null {
  if (!valid(odds) || !(total > 0) || favored < 0 || favored >= odds.length)
    return null;
  const stakes = odds.map((o, i) => (i === favored ? 0 : cents(total / o)));
  stakes[favored] = cents(total - stakes.reduce((a, b) => a + b, 0));
  if (stakes[favored] <= 0) return null;
  return summarize(stakes, odds, total);
}

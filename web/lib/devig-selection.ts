import type { PropBet } from "./refresh-api";

export function selectPropDevig(bet: PropBet, method: string): PropBet | null {
  if (method === "current" || !bet.devig_comparisons?.length) return bet;
  const selected = bet.devig_comparisons.find((row) => row.method === method);
  if (!selected) return null;
  return { ...bet, fair_probability: selected.probability, ev: selected.ev };
}

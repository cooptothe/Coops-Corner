import type { PropBet } from "./refresh-api";

export function passesPropReferences(bet: Pick<PropBet, "sharps">): boolean {
  return bet.sharps.some((book) => book === "fanduel" || book === "pinnacle");
}

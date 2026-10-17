import {
  compareDecimal,
  fixed,
  mulDecimal,
  subDecimal,
} from "../../frontend/format.mjs";

// Straight back wagers only. Unknown commission cannot silently become zero.
export function netBackOdds(odds: string, commission: string | null): string {
  if (
    commission === null ||
    compareDecimal(commission, "0") < 0 ||
    compareDecimal(commission, "1") >= 0 ||
    compareDecimal(odds, "1") <= 0
  )
    throw new Error("Verified straight-bet fee inputs required.");
  return fixed(
    subDecimal(
      "1",
      mulDecimal(subDecimal("1", odds), subDecimal("1", commission)),
    ),
    12,
  );
}

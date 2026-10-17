export function savedWinChance(value: unknown): string {
  const n =
    typeof value === "string" && /^\d{1,3}$/.test(value) ? Number(value) : 0;
  return String(Math.min(100, Math.max(0, n)));
}
export function passesWinChance(probability: number, minimum: string): boolean {
  return (
    Number.isFinite(probability) &&
    probability >= 0 &&
    probability <= 1 &&
    probability * 100 + 1e-10 >= Number(minimum)
  );
}

// The local "My bets" log shared by every tool. Nothing here places a wager.
export const SLIP_KEY = "corner.slip";
const SLIP_LIMIT = 200;

export interface SlipBet {
  at: string;
  matchup: string;
  line: string;
  book: string;
  odds: string;
  stake: string;
}

export type NewSlipBet = Omit<SlipBet, "at">;

export function readSlip(): SlipBet[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(SLIP_KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

// Legs of one play are logged together; each gets its own millisecond so the
// timestamps stay unique.
export function logBets(bets: NewSlipBet[]): void {
  const base = Date.now();
  try {
    const slip = readSlip();
    bets.forEach((bet, i) =>
      slip.push({ ...bet, at: new Date(base + i).toISOString() }),
    );
    localStorage.setItem(SLIP_KEY, JSON.stringify(slip.slice(-SLIP_LIMIT)));
  } catch {}
}

export function clearSlip(): void {
  try {
    localStorage.removeItem(SLIP_KEY);
  } catch {}
}

// Turning a quote's stored sportsbook links into the one URL a person should open.
//
// The server has already checked every link (https, on the sportsbook's own domain). Before one is used it is
// checked again here, after placeholders are filled in, so a bad value can never become a clickable address.
export interface QuoteLinks {
  event?: string | null;
  market?: string | null;
  outcome?: string | null;
}

// betslip: the selection is added to the bet slip. market: the market's page. game: the game's page.
export type LinkKind = "betslip" | "market" | "game";

export interface ResolvedLink {
  url: string | null;
  kind: LinkKind | null;
  // A better link exists but needs the user's state (BetMGM, BetRivers).
  needsState: boolean;
}

export interface LinkOptions {
  // Two-letter US state code, lower case; empty when the user has not chosen one.
  state?: string;
  // Dollar stake to prefill where the sportsbook's link takes one.
  stake?: string;
}

// Sportsbook states shown in the picker (where sports betting is offered).
export const STATES: [string, string][] = [
  ["az", "Arizona"],
  ["ar", "Arkansas"],
  ["co", "Colorado"],
  ["ct", "Connecticut"],
  ["dc", "District of Columbia"],
  ["de", "Delaware"],
  ["fl", "Florida"],
  ["ia", "Iowa"],
  ["il", "Illinois"],
  ["in", "Indiana"],
  ["ks", "Kansas"],
  ["ky", "Kentucky"],
  ["la", "Louisiana"],
  ["ma", "Massachusetts"],
  ["md", "Maryland"],
  ["me", "Maine"],
  ["mi", "Michigan"],
  ["mo", "Missouri"],
  ["ms", "Mississippi"],
  ["nc", "North Carolina"],
  ["ne", "Nebraska"],
  ["nh", "New Hampshire"],
  ["nj", "New Jersey"],
  ["nv", "Nevada"],
  ["ny", "New York"],
  ["oh", "Ohio"],
  ["or", "Oregon"],
  ["pa", "Pennsylvania"],
  ["ri", "Rhode Island"],
  ["sd", "South Dakota"],
  ["tn", "Tennessee"],
  ["va", "Virginia"],
  ["vt", "Vermont"],
  ["wv", "West Virginia"],
  ["wi", "Wisconsin"],
  ["wy", "Wyoming"],
];
const STATE_CODES = new Set(STATES.map(([code]) => code));
export const validState = (value: unknown): string =>
  typeof value === "string" && STATE_CODES.has(value) ? value : "";

const PLACEHOLDER = /\{([^{}]*)\}/g;
const MAX_LENGTH = 2048;

// "54.81" -> "54.81", "25.00" -> "25"; anything that is not a plain positive amount -> null.
function wager(stake: string | undefined): string | null {
  if (!stake || !/^\d{1,9}(\.\d{1,2})?$/.test(stake)) return null;
  const amount = Number(stake);
  if (!(amount > 0)) return null;
  return Number.isInteger(amount) ? String(amount) : amount.toFixed(2);
}

// The URL if it is safe to open, else null.
export function safeUrl(value: string): string | null {
  if (value.length > MAX_LENGTH || /[\s"'<>\\^`{}]/.test(value)) return null;
  try {
    const url = new URL(value);
    if (
      url.protocol !== "https:" ||
      url.username ||
      url.password ||
      url.port ||
      !url.hostname.includes(".")
    )
      return null;
    return url.toString();
  } catch {
    return null;
  }
}

// Fills in one link. null when it needs something we do not have; `needsState` says the state was what is missing.
function fill(
  template: string,
  { state, stake }: LinkOptions,
): { url: string | null; needsState: boolean } {
  let needsState = false;
  let missing = false;
  const filled = template.replace(PLACEHOLDER, (_all, name: string) => {
    if (name === "state") {
      if (state) return state;
      needsState = true;
      return "";
    }
    if (name === "wager" || name === "wagerAmount") {
      const amount = wager(stake);
      if (amount) return amount;
      missing = true;
      return "";
    }
    // Every bet we link is a single selection.
    if (name === "pickType") return "single";
    missing = true;
    return "";
  });
  if (needsState || missing) return { url: null, needsState };
  return { url: safeUrl(filled), needsState: false };
}

export function resolveLink(
  links: QuoteLinks | null | undefined,
  options: LinkOptions = {},
): ResolvedLink {
  const state = validState(options.state);
  const levels: [string | null | undefined, LinkKind][] = [
    [links?.outcome, "betslip"],
    [links?.market, "market"],
    [links?.event, "game"],
  ];
  let needsState = false;
  for (const [template, kind] of levels) {
    if (!template) continue;
    const result = fill(template, { ...options, state });
    if (result.url) return { url: result.url, kind, needsState };
    // A better link is waiting on the state: remember it, but still offer the next best one.
    needsState ||= result.needsState;
  }
  return { url: null, kind: null, needsState };
}

export const hasLinks = (links: QuoteLinks | null | undefined) =>
  !!(links && (links.outcome || links.market || links.event));

export function linkLabel(kind: LinkKind, book: string): string {
  return kind === "betslip"
    ? `Bet on ${book}`
    : kind === "market"
      ? `Open ${book} market`
      : `Open game on ${book}`;
}

export type LinkBlock = "started" | "unavailable" | null;

// Why a link should not be offered at all: the game is under way (these are pre-game prices) or the
// latest update dropped the bet.
export function linkBlock(
  startsAt: string | null | undefined,
  unavailable: boolean,
  now = Date.now(),
): LinkBlock {
  if (unavailable) return "unavailable";
  if (startsAt) {
    const start = new Date(startsAt).getTime();
    if (Number.isFinite(start) && start <= now) return "started";
  }
  return null;
}

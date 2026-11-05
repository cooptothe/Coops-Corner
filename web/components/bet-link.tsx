"use client";
import { SportsbookLink } from "./bet-display";
import { Icon } from "./icon";
import { createContext, useContext, useMemo } from "react";
import {
  STATES,
  hasLinks,
  linkBlock,
  linkLabel,
  resolveLink,
  type QuoteLinks,
} from "../lib/bet-links";
import { useBettingPrefs } from "./betting-prefs";

export const LiveBetLinks = createContext(false);

export function StatePicker({ book }: { book?: string }) {
  const { state, setState } = useBettingPrefs();
  return (
    <label className="field bet-state">
      <span>
        {book ? `YOUR STATE (FOR ${book.toUpperCase()})` : "YOUR STATE"}
      </span>
      <select value={state} onChange={(e) => setState(e.target.value)}>
        <option value="">Choose your state…</option>
        {STATES.map(([code, name]) => (
          <option key={code} value={code}>
            {name}
          </option>
        ))}
      </select>
    </label>
  );
}

// A link to the exact bet at the sportsbook: its betslip when the sportsbook provides one, otherwise the market or
// the game. It is a plain link opened in a new tab, so on a phone the sportsbook's own app can take it over.
export function BetLinkButton({
  links,
  bookLabel,
  stake,
  startsAt,
  unavailable = false,
  allowRetained = false,
  compact = false,
  picker = true,
}: {
  links?: QuoteLinks | null;
  bookLabel: string;
  // Dollars; filled into links that take a stake.
  stake?: string;
  startsAt?: string | null;
  // The latest update dropped this bet.
  unavailable?: boolean;
  // An open calculator may keep its last validated sportsbook link.
  allowRetained?: boolean;
  // A small arrow for table rows; renders nothing when there is nothing to open.
  compact?: boolean;
  // Show the state selector here when the link needs a state. Off when the caller shows one for several buttons.
  picker?: boolean;
}) {
  const { state } = useBettingPrefs();
  const resolved = useMemo(
    () => resolveLink(links, { state, stake }),
    [links, state, stake],
  );
  const live = useContext(LiveBetLinks);
  const block = allowRetained
    ? null
    : linkBlock(live ? null : startsAt, unavailable);

  if (compact) {
    if (block || !resolved.url || !resolved.kind) return null;
    const label = linkLabel(resolved.kind, bookLabel);
    return (
      <SportsbookLink
        book={bookLabel}
        className="bet-link-compact"
        href={resolved.url}
        target="_blank"
        rel="noopener noreferrer"
        referrerPolicy="no-referrer"
        aria-label={`${label} (opens in a new tab or configured display window)`}
        title={`${label}. Check the price there before you bet.`}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
      >
        <Icon name="external" />
      </SportsbookLink>
    );
  }

  const off = (text: string, why: string) => (
    <div className="bet-link">
      <button className="button secondary bet-link-btn" disabled>
        {text}
      </button>
      <small className="kelly-note">{why}</small>
    </div>
  );
  if (block === "unavailable")
    return off(
      `No link: no longer available`,
      "The latest update dropped this bet, so its link was removed.",
    );
  if (block === "started")
    return off(
      "No link: game started",
      "These are pre-game prices, and the sportsbook has moved on.",
    );
  if (!hasLinks(links))
    return off(
      `No ${bookLabel} link`,
      `${bookLabel} did not provide a link for this bet. Find it in the app or site.`,
    );
  if ((!resolved.url || !resolved.kind) && !picker)
    return off(
      `Choose your state for ${bookLabel}`,
      `${bookLabel} links include your state.`,
    );
  if (!resolved.url || !resolved.kind)
    return (
      <div className="bet-link">
        <StatePicker book={bookLabel} />
        <small className="kelly-note">
          {bookLabel} links include your state. Choose it once and it is
          remembered.
        </small>
      </div>
    );
  return (
    <div className="bet-link">
      <SportsbookLink
        book={bookLabel}
        className="button bet-link-btn"
        href={resolved.url}
        target="_blank"
        rel="noopener noreferrer"
        referrerPolicy="no-referrer"
      >
        {linkLabel(resolved.kind, bookLabel)}{" "}
        <span aria-hidden="true">
          <Icon name="external" />
        </span>
        <span className="sr-only">
          {" "}
          (opens in a new tab or configured display window)
        </span>
      </SportsbookLink>
      <small className="kelly-note">
        {resolved.kind === "betslip"
          ? "Adds the selection to the bet slip"
          : resolved.kind === "market"
            ? "Opens the market"
            : "Opens the game"}
        . The sportsbook may ask you to confirm your location. Check the price
        there before you bet.
      </small>
      {resolved.needsState && picker && <StatePicker book={bookLabel} />}
    </div>
  );
}

// One button per leg of a calculator, with a single state selector for all of them.
export function LegLinks({
  legs,
  startsAt,
  unavailable = false,
  allowRetained = false,
}: {
  legs: {
    links?: QuoteLinks | null;
    bookLabel: string;
    label: string;
    stake?: string;
  }[];
  startsAt?: string | null;
  unavailable?: boolean;
  // An open calculator may keep its last validated sportsbook link.
  allowRetained?: boolean;
}) {
  const { state } = useBettingPrefs();
  const needsState = legs.some(
    (l) => resolveLink(l.links, { state, stake: l.stake }).needsState,
  );
  return (
    <div className="bet-links">
      {legs.map((l, i) => (
        <BetLinkButton
          key={`${i}-${l.bookLabel}-${l.label}`}
          links={l.links}
          bookLabel={l.bookLabel}
          stake={l.stake}
          startsAt={startsAt}
          unavailable={unavailable}
          allowRetained={allowRetained}
          picker={false}
        />
      ))}
      {needsState && <StatePicker />}
    </div>
  );
}

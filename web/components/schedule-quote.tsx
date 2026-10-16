"use client";
import { american, point as signed } from "../../frontend/format.mjs";
import { linkBlock, linkLabel, resolveLink } from "../lib/bet-links";
import type { BestPrice, LineMarket } from "../lib/schedule";
import { useBettingPrefs } from "./betting-prefs";
import { StatePicker } from "./bet-link";
import { PlacedBadge, usePlaced } from "./placed";

export function ScheduleQuote({
  market,
  side,
  price,
  bookName,
  startsAt,
}: {
  market: LineMarket;
  side: string;
  price: BestPrice | undefined;
  bookName: (id: string) => string;
  startsAt: string;
}) {
  const { state } = useBettingPrefs();
  const placed = usePlaced(
    price ? [{ ref: price.ref, bookLabel: bookName(price.bookId) }] : [],
  );
  if (!price) return <div className="sched-quote empty">—</div>;
  const book = bookName(price.bookId);
  const odds = american(String(price.decimal));
  const line =
    market === "h2h" || price.point == null
      ? ""
      : market === "totals"
        ? `${side === "over" ? "O" : "U"} ${price.point}`
        : price.point === 0
          ? "PK"
          : signed(String(price.point));
  const resolved = resolveLink(price.links, { state });
  const started = linkBlock(startsAt, false);
  const label = `${market === "h2h" ? "Moneyline" : market === "spreads" ? "Spread" : "Total"}, ${side}, ${line} ${odds}, ${book}`;
  const content = (
    <>
      {line && <span className="sched-line">{line}</span>}
      <span className="sched-price-book">
        <b className="sched-price">{odds}</b>
        <small className="sched-book">{book}</small>
      </span>
      <PlacedBadge state={placed} />
    </>
  );
  if (!started && resolved.url && resolved.kind)
    return (
      <a
        className="sched-quote sched-market-link"
        href={resolved.url}
        target="_blank"
        rel="noopener noreferrer"
        referrerPolicy="no-referrer"
        aria-label={`${label}. ${linkLabel(resolved.kind, book)} (opens in a new tab)`}
        title={`${linkLabel(resolved.kind, book)}. Check the price there before you bet.`}
      >
        {content}
        <span className="sched-link-arrow" aria-hidden="true">
          ↗
        </span>
      </a>
    );
  return (
    <>
      <div
        className="sched-quote"
        title={
          started
            ? "No link: game started"
            : resolved.needsState
              ? `Choose your state to open ${book}`
              : `${book} did not provide a link for this price`
        }
      >
        {content}
      </div>
      {!started && resolved.needsState && <StatePicker book={book} />}
    </>
  );
}

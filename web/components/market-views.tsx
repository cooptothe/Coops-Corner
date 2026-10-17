"use client";
import { useEffect, useRef } from "react";
import {
  MARKETS,
  TITLES,
  american,
  percent,
  usd,
  selection,
  date,
  sport,
  tone,
  compareDecimal,
  mulDecimal,
  subDecimal,
  divDecimal,
  ageLabel,
} from "../../frontend/format.mjs";
import type { Book, Game, Quote, ToolRow, Leg } from "../lib/contracts";

export function rowLegs(row: ToolRow): Leg[] {
  if (row.kind === "positive_ev")
    return [
      {
        quote_id: row.calculation.target_quote_id,
        stake: row.calculation.stake,
      },
    ];
  if ("legs" in row.calculation) return row.calculation.legs;
  const c = row.calculation;
  return [
    { quote_id: c.back_quote_id, stake: c.back_stake },
    { quote_id: c.lay_quote_id, stake: c.lay_stake },
  ];
}
const bookName = (books: Book[], id?: string) =>
  books
    .find((b) => b.id === id)
    ?.name.replace("Demo ", "")
    .replace("Reference ", "Ref ") ??
  id ??
  "—";
const KELLY_FRACTION = "0.25";
// Quarter-Kelly stake on a back bet, with no cap. Lay targets get no suggestion.
function kellyStake(
  row: Extract<ToolRow, { kind: "positive_ev" }>,
  quotes: Map<string, Quote>,
  bankroll?: string,
) {
  const q = quotes.get(row.calculation.target_quote_id);
  const edge = row.conditional_ev_ratio;
  if (!bankroll || !q || !edge || q.market_key.endsWith("_lay")) return null;
  const net = subDecimal(q.decimal_odds, "1");
  if (compareDecimal(edge, "0") <= 0 || compareDecimal(net, "0") <= 0)
    return null;
  const fraction = mulDecimal(divDecimal(edge, net), KELLY_FRACTION);
  return mulDecimal(bankroll, fraction);
}
function sharpBooks(
  row: Extract<ToolRow, { kind: "positive_ev" }>,
  books: Book[],
) {
  return row.calculation.reference_books
    .map((b) => bookName(books, b.sportsbook_id))
    .join(", ");
}
export function Cards({
  rows,
  games,
  quotes,
  books,
  onDetail,
  stake,
  bankroll,
}: {
  rows: ToolRow[];
  games: Game[];
  quotes: Map<string, Quote>;
  books: Book[];
  onDetail: (row: ToolRow) => void;
  stake?: string;
  bankroll?: string;
}) {
  return (
    <div className="tool-table-wrap">
      <table className="tool-table">
        <thead>
          <tr>
            <th scope="col">
              {rows[0]?.kind === "positive_ev"
                ? "EV"
                : rows[0]?.kind === "middle"
                  ? "If it hits"
                  : "Profit"}
            </th>
            <th scope="col">Event</th>
            <th scope="col">Place these bets</th>
            <th scope="col">
              {rows[0]?.kind === "positive_ev" ? "Fair odds" : "Total stake"}
            </th>
            <th scope="col">Updated</th>
            <th scope="col" />
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const g = games.find((g) => g.id === row.game_id),
              legs = rowLegs(row),
              base =
                row.kind === "positive_ev"
                  ? row.calculation.stake
                  : row.capital_required,
              kelly =
                row.kind === "positive_ev"
                  ? kellyStake(row, quotes, bankroll)
                  : null,
              target = kelly ?? stake,
              factor =
                target && compareDecimal(base, "0") > 0
                  ? divDecimal(target, base)
                  : "1",
              s = (v: string | null) =>
                v == null ? null : mulDecimal(v, factor),
              ev = row.kind === "positive_ev" ? row : null,
              mid = row.kind === "middle" ? row : null,
              cover = row.kind === "arbitrage" ? row : null,
              headline = ev
                ? ev.conditional_ev_ratio
                : mid
                  ? s(mid.calculation.payoff.maximum_modeled_profit)
                  : cover && compareDecimal(base, "0") > 0
                    ? divDecimal(
                        cover.calculation.minimum_decisive_profit,
                        base,
                      )
                    : null,
              fairProbability = ev?.calculation.conditional_fair_probability;
            return (
              <tr className="tool-row" key={row.id}>
                <td className="tool-edge">
                  <strong className={`edge-value ${tone(headline ?? "0")}`}>
                    {mid ? usd(headline) : percent(headline, true)}
                  </strong>
                  <small>
                    {ev
                      ? `${usd(s(ev.calculation.conditional_expected_profit))} expected on ${usd(s(ev.calculation.stake))}`
                      : mid
                        ? `Window ${mid.calculation.double_win_ranges.map(([a, b]) => `${a ?? "−∞"}–${b ?? "∞"}`).join(", ")}`
                        : `${usd(s(cover!.calculation.minimum_decisive_profit))} if a side wins`}
                  </small>
                  {mid && (
                    <small className="negative">
                      Miss: {usd(s(row.minimum_profit))}
                    </small>
                  )}
                </td>
                <td className="tool-event">
                  <span className="event-sport">
                    {g?.competition ?? sport(g?.sport_key ?? "")}
                  </span>
                  <strong>{g?.name}</strong>
                  <time>{g ? date(g.starts_at) : ""}</time>
                  <span className="market-chip">{MARKETS[row.market_key]}</span>
                </td>
                <td className="tool-legs">
                  {legs.map((leg, i) => {
                    const q = quotes.get(leg.quote_id);
                    return (
                      <div className="bet-leg" key={leg.quote_id}>
                        <span className="book-badge">
                          {bookName(books, q?.sportsbook_id)}
                        </span>
                        <div className="leg-selection">
                          <strong>{selection(q)}</strong>
                          <small>
                            {q?.market_key.endsWith("_lay") ? "Lay" : "Bet"}{" "}
                            {usd(s(leg.stake))}
                            {q?.commission_rate != null &&
                            compareDecimal(q.commission_rate, "0") > 0
                              ? ` · ${percent(q.commission_rate)} commission`
                              : ""}
                          </small>
                        </div>
                        <span className="american-line">
                          {american(q?.decimal_odds)}
                        </span>
                        <span className="sr-only">Leg {i + 1}</span>
                      </div>
                    );
                  })}
                  <small className="card-footnote">
                    {ev
                      ? `Fair win chance ${percent(fairProbability)}, no-vig from ${sharpBooks(ev, books)}. ${kelly ? "Stake is quarter-Kelly of bankroll." : "Example stake."}`
                      : mid
                        ? "Middle EV is not estimated; it depends on how often the result lands in the window."
                        : cover &&
                          "lay_liability" in cover.calculation &&
                          `Lay liability ${usd(s(cover.calculation.lay_liability))}`}
                    {cover && "refund_profit" in cover.calculation && (
                      <> Modeled minimum {usd(s(row.minimum_profit))}</>
                    )}
                  </small>
                </td>
                <td className="tool-stake">
                  {ev && fairProbability ? (
                    <>
                      <strong>
                        {american(divDecimal("1", fairProbability))}
                      </strong>
                      <small>
                        {kelly ? "Suggested" : "Stake"}{" "}
                        {usd(s(ev.calculation.stake))}
                      </small>
                    </>
                  ) : (
                    <>
                      <strong>{usd(s(row.capital_required))}</strong>
                      <small>Capital required</small>
                    </>
                  )}
                </td>
                <td className="tool-age">{ageLabel(row.oldest_observed_at)}</td>
                <td>
                  <button
                    className="inspect-card"
                    onClick={() => onDetail(row)}
                    aria-label={`View calculation for ${legs.map((l) => selection(quotes.get(l.quote_id))).join(" / ")}`}
                  >
                    Payoffs ↗
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
export function OddsMatrix({
  quotes,
  books,
  onPromo,
}: {
  quotes: Quote[];
  books: Book[];
  onPromo: (q: Quote) => void;
}) {
  const groups = new Map<string, Quote[]>();
  for (const q of quotes) {
    const key = JSON.stringify([q.contract_id, q.market_key, q.selection_id]);
    groups.set(key, [...(groups.get(key) ?? []), q]);
  }
  const rows = [...groups.values()].sort(
    (a, b) =>
      Object.keys(MARKETS).indexOf(a[0].market_key) -
        Object.keys(MARKETS).indexOf(b[0].market_key) ||
      a[0].contract_id.localeCompare(b[0].contract_id) ||
      selection(a[0]).localeCompare(selection(b[0])),
  );
  return (
    <div className="table-wrap odds-scroll">
      <table className="odds-matrix">
        <caption className="sr-only">
          American odds by exact contract and sportsbook. Best quoted compares
          raw prices before commission.
        </caption>
        <thead>
          <tr>
            <th scope="col">Selection / exact line</th>
            <th scope="col">Best quoted</th>
            {books.map((b) => (
              <th scope="col" key={b.id}>
                <span className="book-initial">
                  {b.name
                    .replace("Demo ", "")
                    .replace("Reference ", "R")
                    .slice(0, 3)}
                </span>
                {b.name.replace("Demo ", "")}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((group) => {
            const first = group[0],
              lay = first.market_key.endsWith("_lay"),
              best = group.reduce((a, b) =>
                compareDecimal(a.decimal_odds, b.decimal_odds) *
                  (lay ? -1 : 1) >=
                0
                  ? a
                  : b,
              );
            return (
              <tr
                key={JSON.stringify([
                  first.contract_id,
                  first.market_key,
                  first.selection_id,
                ])}
              >
                <th scope="row">
                  <strong>{selection(first)}</strong>
                  <small>
                    {MARKETS[first.market_key]} · {first.contract_id}
                  </small>
                </th>
                <td className="best-line">
                  <strong>{american(best.decimal_odds)}</strong>
                  <small>
                    {books
                      .find((b) => b.id === best.sportsbook_id)
                      ?.name.replace("Demo ", "")}
                  </small>
                </td>
                {books.map((b) => {
                  const q = group.find((q) => q.sportsbook_id === b.id);
                  return q ? (
                    <td
                      key={b.id}
                      className={
                        compareDecimal(q.decimal_odds, best.decimal_odds) === 0
                          ? "price-best"
                          : ""
                      }
                    >
                      {lay ? (
                        <span className="odds-cell">
                          <strong>{american(q.decimal_odds)}</strong>
                          <small>
                            Lay ·{" "}
                            {q.commission_rate == null
                              ? "fee unverified"
                              : `${percent(q.commission_rate)} fee`}
                          </small>
                        </span>
                      ) : (
                        <button
                          className="odds-cell"
                          onClick={() => onPromo(q)}
                          aria-label={`Use ${b.name} ${selection(q)} ${american(q.decimal_odds)} in promo`}
                        >
                          <strong>{american(q.decimal_odds)}</strong>
                          <small>Use in promo ↗</small>
                        </button>
                      )}
                    </td>
                  ) : (
                    <td
                      className="missing-line"
                      key={b.id}
                      aria-label="No quote"
                    >
                      —
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
export function Metrics({ values }: { values: [string, string][] }) {
  return (
    <dl className="detail-metrics">
      {values.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}
export function Payoffs({ rows }: { rows: [string, string, string?][] }) {
  return (
    <>
      <div className="outcome-strip">
        {rows.map(([label, value, token]) => (
          <div className="outcome-tile" key={label}>
            <small>{label}</small>
            <strong className={tone(value)}>{usd(value)}</strong>
            {token !== undefined && <small>Token face {usd(token)}</small>}
          </div>
        ))}
      </div>
      <div className="table-wrap">
        <table className="small-table">
          <thead>
            <tr>
              <th>Outcome</th>
              <th>Cash profit</th>
              {rows.some((r) => r[2] !== undefined) && <th>Noncash face</th>}
            </tr>
          </thead>
          <tbody>
            {rows.map(([label, value, token]) => (
              <tr key={label}>
                <td>{label}</td>
                <td className={`mono ${tone(value)}`}>{usd(value)}</td>
                {token !== undefined && <td className="mono">{usd(token)}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
export function Details({
  row,
  quotes,
  books,
  live,
  onClose,
}: {
  row: ToolRow;
  quotes: Map<string, Quote>;
  books: Book[];
  live?: boolean;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    const previous = document.activeElement as HTMLElement | null;
    dialog?.showModal();
    return () => {
      dialog?.close();
      previous?.focus();
    };
  }, []);
  let values: [string, string][] = [],
    payoffs: [string, string][] = [];
  if (row.kind === "positive_ev") {
    const c = row.calculation;
    values = [
      ["Conditional EV", percent(row.conditional_ev_ratio, true)],
      ["Capital at risk", usd(c.capital_at_risk)],
      ["Conditional expected profit", usd(c.conditional_expected_profit)],
      ["Unconditional EV", "Not estimated"],
    ];
  } else if (row.kind === "middle") {
    values = [
      ["Capital required", usd(row.capital_required)],
      ["Worst modeled payoff", usd(row.minimum_profit)],
      [
        "Best modeled payoff",
        usd(row.calculation.payoff.maximum_modeled_profit),
      ],
      ["Middle EV", "Not estimated"],
    ];
    payoffs = row.calculation.payoff.states.map((s) => [
      s.state_id === "common_refund"
        ? "Common refund"
        : s.state_id
            .replace("score:", "")
            .replace("-inf:", "≤ ")
            .replace(":+inf", " or more")
            .replaceAll(":", "–"),
      s.net_profit,
    ]);
  } else {
    const c = row.calculation;
    values = [
      ["Capital required", usd(row.capital_required)],
      ["Decisive minimum", usd(c.minimum_decisive_profit)],
      ["Modeled minimum", usd(c.minimum_modeled_profit)],
    ];
    payoffs =
      "legs" in c
        ? c.legs.map((l) => [
            selection(quotes.get(l.quote_id)),
            l.profit_if_selection_wins,
          ])
        : [
            ["Selection wins", c.profit_if_selection_wins],
            ["Selection loses", c.profit_if_selection_loses],
          ];
    if (c.refund_profit !== null)
      payoffs.push(["Common refund", c.refund_profit]);
    if ("lay_liability" in c)
      values.push(["Lay liability", usd(c.lay_liability)]);
  }
  return (
    <dialog
      ref={ref}
      aria-labelledby="detail-title"
      onClose={onClose}
      onCancel={onClose}
      onClick={(e) => {
        if (e.target === e.currentTarget) {
          const r = e.currentTarget.getBoundingClientRect();
          if (
            e.clientX < r.left ||
            e.clientX > r.right ||
            e.clientY < r.top ||
            e.clientY > r.bottom
          )
            onClose();
        }
      }}
    >
      <div className="dialog-header">
        <div>
          <p className="eyebrow">CALCULATION DETAILS</p>
          <h2 id="detail-title">{TITLES[row.kind]}</h2>
        </div>
        <button
          className="icon-button"
          onClick={onClose}
          aria-label="Close details"
        >
          ×
        </button>
      </div>
      <div id="detail-body">
        <p className="notice">
          {live
            ? "Calculated from stored pre-game quotes, not live prices. Re-check every price at the sportsbook; availability and settlement-rule equivalence are unverified."
            : "Synthetic fixture calculation. Phase and availability are unverified."}
        </p>
        <Metrics values={values} />
        {row.kind === "positive_ev" && (
          <>
            <h3>Conditional probability basis</h3>
            <p className="muted">
              Named selection wins given decisive settlement. For a lay, this is
              the chance the selection wins, not the chance the lay wins.
              Reference books are normalized separately, then equally weighted.
            </p>
            <div className="table-wrap">
              <table className="small-table">
                <thead>
                  <tr>
                    <th>Reference book</th>
                    <th>Selection probabilities</th>
                  </tr>
                </thead>
                <tbody>
                  {row.calculation.reference_books.map((b) => (
                    <tr key={b.sportsbook_id}>
                      <td>
                        {
                          books.find((book) => book.id === b.sportsbook_id)
                            ?.name
                        }
                      </td>
                      <td>
                        {b.probabilities.map(([id, p]) => (
                          <div key={id}>
                            {quotes.get(
                              b.quote_ids.find(
                                (q) => quotes.get(q)?.selection_id === id,
                              ) ?? "",
                            )?.selection_name ?? id}
                            : {percent(p)}
                          </div>
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
        {payoffs.length > 0 && <Payoffs rows={payoffs} />}
        <h3>Exact source quotes</h3>
        <div className="quote-evidence">
          {row.quote_ids.map((id) => {
            const q = quotes.get(id);
            return (
              <div key={id}>
                <span className="book-badge">
                  {books.find((b) => b.id === q?.sportsbook_id)?.name}
                </span>
                <span>{selection(q)}</span>
                <strong>{american(q?.decimal_odds)}</strong>
              </div>
            );
          })}
        </div>
        <details className="raw">
          <summary>Inspect full calculation (raw decimal API values)</summary>
          <pre>{JSON.stringify(row.calculation, null, 2)}</pre>
        </details>
      </div>
    </dialog>
  );
}

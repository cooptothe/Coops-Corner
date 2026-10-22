"use client";
import { memo } from "react";
import LabResearchBrowser from "./lab-research-browser";
import { LabInsight } from "./lab-insight";
import { LabChart } from "./lab-chart";
import { labDate, labLeg, labQuoteCurrent } from "../lib/lab";
import { useParlay } from "./parlay-builder";
import { PROP_BOOKS } from "../lib/bookmakers";
import { BetLinkButton } from "./bet-link";
import { american } from "../../frontend/format.mjs";
import { type TrendContract, type TrendReport } from "../lib/trends-api";

const pct = (value: number | null) =>
  value == null ? "Unavailable" : `${(value * 100).toFixed(1)}%`;
const numeric = (value: number | null) =>
  value == null ? "—" : value.toFixed(1);
const marketName = (key: string) =>
  key.replace(/^(player|batter|pitcher)_/, "").replaceAll("_", " ");

const bookName = (key: string) =>
  PROP_BOOKS.find((book) => book.id === key)?.name ?? key;

function AddToParlay({ contract }: { contract: TrendContract }) {
  const parlay = useParlay();
  const leg = labLeg(contract);
  if (!parlay || !leg) return null;
  const selected = parlay.selected(leg.key);
  const wrongBook = parlay.draft.active && parlay.draft.book !== leg.book;
  return (
    <button
      type="button"
      className="button secondary"
      disabled={wrongBook}
      onClick={() =>
        parlay.draft.active ? parlay.toggle(leg) : parlay.start()
      }
    >
      {wrongBook
        ? `Choose ${bookName(parlay.draft.book)}`
        : selected
          ? "Remove from parlay"
          : parlay.draft.active
            ? "Add to parlay"
            : "Build a parlay"}
    </button>
  );
}

function TrendResultsView({
  report,
  quotes,
  onPick,
}: {
  report: TrendReport;
  quotes?: TrendContract[];
  onPick?: (id: string) => void;
}) {
  return (
    <div className="trend-results">
      <header className="lc-selected-offer">
        <p>
          {labQuoteCurrent(report.contract)
            ? "Selected offer"
            : "Saved research line — not current odds"}{" "}
          · {bookName(report.contract.book)}{" "}
          {report.contract.price_kind === "indicative"
            ? "Indicative price; check lineup payout"
            : american(report.contract.price)}{" "}
          · {report.contract.side}{" "}
          {["Over", "Under"].includes(report.contract.side)
            ? report.contract.point
            : ""}
        </p>
        {report.contract.observed_at && (
          <p className="trk-muted">
            Quote checked {labDate(report.contract.observed_at)}. Confirm the
            current price at the book.
          </p>
        )}
        {labQuoteCurrent(report.contract) &&
          report.contract.links &&
          report.contract.starts_at && (
            <BetLinkButton
              links={report.contract.links}
              bookLabel={bookName(report.contract.book)}
              startsAt={report.contract.starts_at}
            />
          )}
        <AddToParlay contract={report.contract} />
      </header>
      <LabChart
        key={report.contract.id}
        report={report}
        quotes={quotes}
        onPick={onPick}
        renderAction={(quote) => <AddToParlay contract={quote} />}
      />
      <details className="lc-model-context">
        <summary>Projection &amp; research context</summary>
        <LabInsight report={report} />
      </details>
      <details className="trend-model">
        <summary>Advanced model details</summary>
        <h4>Historical estimate</h4>
        <p>
          Smoothed historical estimate{" "}
          <strong>{pct(report.model_probability)}</strong> · Price break-even{" "}
          <strong>{pct(report.break_even_probability)}</strong>
        </p>
        <p>
          Provisional return after modeled fees:{" "}
          <strong>{pct(report.model_ev)}</strong> per unit staked.
        </p>
        <p className="trk-muted">
          This is not calibrated +EV. It does not replace the market-reference
          EV feed. Matchup and news are context, not fitted probability
          adjustments.
        </p>
        {report.workload_change != null && (
          <p>
            Recent workload change: {pct(report.workload_change)} (last five vs
            previous five).
          </p>
        )}
        <ul>
          {report.flags.map((flag) => (
            <li key={flag}>{flag}</li>
          ))}
        </ul>
      </details>
      <details>
        <summary>Game-by-game evidence</summary>
        <div className="trend-table">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Opponent</th>
                <th>Result</th>
                <th>{report.workload_label}</th>
                <th>Season</th>
              </tr>
            </thead>
            <tbody>
              {report.games.map((game) => (
                <tr key={game.id}>
                  <td>
                    {game.source_url ? (
                      <a
                        href={game.source_url}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {labDate(game.date, true)}
                      </a>
                    ) : (
                      labDate(game.date, true)
                    )}
                  </td>
                  <td>{game.opponent}</td>
                  <td>{game.value}</td>
                  <td>{game.workload ?? "—"}</td>
                  <td>{game.season}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
      <details>
        <summary>Historical model check</summary>
        <p>
          {report.historical_replay.held_out_games} chronological holdout games
          · Brier score {numeric(report.historical_replay.brier)} · Log loss{" "}
          {numeric(report.historical_replay.log_loss)}
        </p>
        <p className="trk-muted">
          This replays the current line on past results. It does not use
          archived historical prices or prove betting profitability.
        </p>
      </details>
      <section>
        <h4>Player &amp; matchup news</h4>
        <p>
          <a
            href={report.availability_url}
            target="_blank"
            rel="noopener noreferrer"
          >
            Check the latest injury report
          </a>
        </p>
        {report.news_status !== "available" ? (
          <p>
            News is temporarily unavailable. Check injury and lineup reports
            independently.
          </p>
        ) : report.news.length ? (
          <ul>
            {report.news.map((item) => (
              <li key={item.url}>
                <a href={item.url} target="_blank" rel="noopener noreferrer">
                  {item.headline}
                </a>
                <small> · {labDate(item.published)}</small>
              </li>
            ))}
          </ul>
        ) : (
          <p>
            No matching headlines in the cached source. This does not confirm
            the player is healthy or starting.
          </p>
        )}
      </section>
      <footer className="trk-muted">
        <p>{report.coverage}</p>
        <p>
          {report.source} · Stats checked {labDate(report.stats_fetched_at)}
          {report.news_fetched_at &&
            ` · News checked ${labDate(report.news_fetched_at)}`}
        </p>
      </footer>
    </div>
  );
}

export const TrendResults = memo(TrendResultsView);

export default function LabResearch({
  selectedBetId,
}: {
  selectedBetId: string | null;
}) {
  return (
    <LabResearchBrowser
      selectedBetId={selectedBetId}
      renderReport={(report, quotes, onPick) => (
        <TrendResults report={report} quotes={quotes} onPick={onPick} />
      )}
    />
  );
}

"use client";
import type { TrendReport } from "../lib/trends-api";

const percent = (value: number | null | undefined) =>
  value == null || !Number.isFinite(value)
    ? "Not available"
    : `${(value * 100).toFixed(1)}%`;

export function LabInsight({ report }: { report: TrendReport }) {
  const recent = report.windows.last_10 ?? report.windows["10"];
  const projection = report.projection;
  const modeled = projection?.status === "research_only";
  const offered =
    `${report.contract.side} ${["Over", "Under"].includes(report.contract.side) ? report.contract.point : ""}`.trim();
  return (
    <section className="lab-insight" aria-label="Research at a glance">
      <header>
        <div>
          <p className="eyebrow">THE QUICK READ</p>
          <h3>What to know</h3>
        </div>
        <span className="lab-insight-tag">{offered} · selected offer</span>
      </header>
      <div className="lab-insight-cards">
        <article>
          <h4>Recent results</h4>
          <strong>
            {recent?.games
              ? `${recent.wins} of ${recent.games}`
              : "History unavailable"}
          </strong>
          <p>
            {recent?.games
              ? `games cleared this side at the selected line${recent.pushes ? `; ${recent.pushes} ended on the line` : ""}.`
              : "Choose another player or check back when game logs are available."}
          </p>
          <small>
            Past results describe form, not the next game's win chance.
          </small>
        </article>
        <article>
          <h4>Model outlook</h4>
          <strong>
            {modeled ? percent(projection.probability) : "More data needed"}
          </strong>
          <p>
            {modeled
              ? "Estimated chance for this offer, based on available game logs."
              : "There isn't enough supported data for a reliable model estimate here."}
          </p>
          {modeled && projection.projected_mean != null && (
            <p>
              Projected average: <b>{projection.projected_mean.toFixed(1)}</b>
            </p>
          )}
          <small>
            Research estimate. Lineup, role and matchup effects are not fitted.
          </small>
        </article>
        <article>
          <h4>Before you bet</h4>
          <strong>Check price &amp; lineup</strong>
          <p>
            {report.news_status === "available"
              ? "Read the latest news below and confirm the player is starting."
              : "News isn't available here. Check injuries and starting status at the source."}
          </p>
          <small>
            Confirm the current odds and settlement rules at your sportsbook.
          </small>
        </article>
      </div>
      <p className="lab-insight-note">
        This summary uses the selected sportsbook offer. Chart filters and
        what-if lines change historical results only.
      </p>
      {projection && (
        <details className="lab-estimate-details">
          <summary>How to read the estimate</summary>
          {modeled ? (
            <>
              <p>
                Estimated win chance: <b>{percent(projection.probability)}</b>.
                Push / refund chance:{" "}
                <b>{percent(projection.push_probability)}</b>.
              </p>
              <p>
                Estimated return after modeled fees:{" "}
                <b>{percent(projection.model_ev)}</b>. This is not a validated
                +EV recommendation.
              </p>
              <p>
                A hit rate counts past results. A model estimate uses historical
                data to estimate a future outcome. Neither guarantees a win.
              </p>
              <details>
                <summary>Technical assumptions</summary>
                {projection.models?.map((model) => (
                  <p key={model.method}>
                    {model.method.replaceAll("_", " ")}: {percent(model.win)}{" "}
                    estimated chance; {percent(model.ev)} modeled return.
                  </p>
                ))}
                <ul>
                  {projection.assumptions?.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </details>
            </>
          ) : (
            <p>
              {projection.reason?.replaceAll("_", " ") ??
                "More context is required for this projection."}
            </p>
          )}
        </details>
      )}
    </section>
  );
}

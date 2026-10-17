"use client";
import { useEffect, useState } from "react";
import { notifyUnauthorized } from "../lib/auth-api";
interface Coverage {
  retained_quotes: number;
  outcomes: Record<string, number>;
  catalog_market_count: number;
  markets: {
    sport_key: string;
    market: string;
    label: string;
    quotes: number;
    priced: number;
    projection: { method: string; requires: string[] };
  }[];
}
function CoverageReport() {
  const [report, setReport] = useState<Coverage | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/refresh/v1/props/coverage", {
      cache: "no-store",
      signal: AbortSignal.any([controller.signal, AbortSignal.timeout(30000)]),
    })
      .then(async (response) => {
        if (response.status === 401) notifyUnauthorized();
        if (!response.ok) throw Error("Coverage unavailable");
        const result = await response.json();
        if (!controller.signal.aborted) setReport(result);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, []);
  if (failed)
    return (
      <p className="trk-muted">Market coverage is temporarily unavailable.</p>
    );
  if (!report) return null;
  return (
    <div>
      <h3>
        Coverage: {report.retained_quotes} retained selections,{" "}
        {report.outcomes.market_priced ?? 0} market-priced
      </h3>
      <p>
        Every retained selection is assessed. Missing data does not become an
        invented edge. The catalog currently defines{" "}
        {report.catalog_market_count} market entries across sports.
      </p>
      <p>
        {report.outcomes.projection_or_reference_context_needed ?? 0} need
        projection or reference context;{" "}
        {report.outcomes.execution_fee_or_payoff_missing ?? 0} need fee or
        payout details; {report.outcomes.undocumented_market ?? 0} need market
        definitions.
      </p>
      <ul>
        {report.markets.map((m) => (
          <li key={`${m.sport_key}:${m.market}`}>
            <strong>{m.label}</strong> ({m.sport_key}): {m.priced}/{m.quotes}{" "}
            market-priced. Projection method:{" "}
            {m.projection.method.replaceAll("_", " ")}. Needs{" "}
            {m.projection.requires
              .map((v) => v.replaceAll("_", " "))
              .join(", ")}
            .
          </li>
        ))}
      </ul>
      <p>
        Coverage is limited to retained provider quotes. Projection estimates
        are research, not validated betting opportunities.
      </p>
    </div>
  );
}

export default function LabCoverage() {
  const [requested, setRequested] = useState(false);
  return (
    <details
      className="trk-card"
      onToggle={(event) => {
        if (event.currentTarget.open) setRequested(true);
      }}
    >
      <summary>Market coverage</summary>
      {requested && <CoverageReport />}
    </details>
  );
}

"use client";
import { useDeferredValue, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { PersonalNav } from "./personal-nav";
import { UserMenu } from "./auth-provider";
import { GUIDES, TOOL_NOTES } from "../lib/help-content";

const EXTRA = [
  {
    id: "live",
    title: "Live: Play, Pause and fresh odds",
    body: "Play shows ESPN-reported games in progress. Pause shows reported halftime, period breaks, intermissions, delays and timeouts. A missing bookmaker price is not a game stoppage. Free game status is checked every 15 seconds while Live is open and may lag actual play. Stale or unmatched statuses are excluded from Play/Pause; use All games to see them. Brief timeouts may be missed. Odds refresh independently every 60 seconds, expire after 90 seconds of source age, and can be unavailable during a break. Live access is included for friend accounts and the owner.",
  },
  {
    id: "lab",
    title: "The Lab: research player props",
    body: "Choose a league, game, player and market. Adjust the line and compare L5, L10, L20 and season game logs. Hit rates describe historical outcomes, not a calibrated chance of winning the next game. Equality at an integer line is a push, not an Over win. Splits use available recorded data. Research lines may be older than actionable feed prices; check timestamps and sportsbook rules. News and injury availability can change quickly.",
  },
  {
    id: "parlays",
    title: "Parlays and tracking",
    body: "Enter parlay mode, select a sportsbook and add legs. Build the ticket in the sportsbook and enter its accepted combined American odds and stake. Same-game legs can be correlated: multiplying individual probabilities does not establish the combined chance or payout. Record the ticket only after you place it. Opening a link never places a wager.",
  },
  {
    id: "tracker",
    title: "Tracker, bankroll and CLV",
    body: "Log accepted odds, stake and placement time. Choose Today, Yesterday or another performance window to filter both the results and bet list. Deposits and withdrawals affect bankroll, not betting profit. CLV compares the accepted price with a captured closing reference on the exact line; missing closes stay pending or unavailable. Live progress is informational; verify final grading and settlement at your sportsbook.",
  },
  {
    id: "links",
    title: "Sportsbook links and account settings",
    body: "Links open the exact betslip when supplied, otherwise the market or event. Choose your betting state in Account for state-specific books. The sportsbook controls location checks, limits, acceptance and final odds. Live links remain available after kickoff when a fresh live quote has a valid provider URL. Missing links are not invented.",
  },
  {
    id: "bankroll",
    title: "Sharp betting basics",
    body: "Expected value is probability × net decimal return − 1 for a no-push binary bet, with fees and push settlement handled where supported. Devig methods estimate fair probabilities by removing bookmaker margin; they depend on reference quality and assumptions. An estimated edge does not guarantee profit. Higher hit rate does not imply better value. Use a separate bankroll, small consistent stakes, and account for correlated exposure; never increase stakes to chase losses. Arbitrage and middles require compatible settlement and timely acceptance of every leg.",
  },
  {
    id: "install",
    title: "Mobile setup and troubleshooting",
    body: "On iPhone, open Safari, tap Share, then Add to Home Screen. On Android, use Chrome’s Install app or Add to Home screen. Internet access is required. Navigation uses the same order and labels throughout the app; swipe the mobile navigation bar to reach more tools. Filters collapse on small screens. If a feed is empty, check its filters, selected devig method and timestamps. A service error is different from no qualifying bets. Contact admin@coopscorner.tech if an action fails.",
  },
];
export default function HelpPage() {
  const [search, setSearch] = useState("");
  const query = useDeferredValue(search.trim().toLowerCase());
  const sections = [
    ...Object.entries(GUIDES).map(([id, [title, body]]) => ({
      id,
      title,
      body,
    })),
    ...EXTRA,
  ];
  const visible = sections.filter((s) =>
    [s.title, s.body, ...(TOOL_NOTES[s.id] ?? [])]
      .join(" ")
      .toLowerCase()
      .includes(query),
  );
  return (
    <main id="main" tabIndex={-1} className="personal-page help-page">
      <header className="personal-header">
        <Link
          href="/positive_ev"
          className="personal-brand"
          aria-label="The Corner home"
        >
          <Image
            src="/assets/corner-logo.png"
            alt="The Corner"
            width={64}
            height={64}
          />
        </Link>
        <div>
          <h1>Help &amp; guide</h1>
        </div>
        <div className="page-actions">
          <UserMenu />
        </div>
      </header>
      <PersonalNav current="help" />
      <label className="field help-search">
        <span>Find help</span>
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search tools, odds, bankroll…"
        />
      </label>
      <nav className="help-topics" aria-label="Help topics">
        {visible.map((s) => (
          <a key={s.id} href={"#" + s.id}>
            {s.title}
          </a>
        ))}
      </nav>
      <div className="help-sections">
        {visible.map((s) => (
          <section key={s.id} id={s.id} className="trk-card">
            <h2>{s.title}</h2>
            <p>{s.body}</p>
            {TOOL_NOTES[s.id]?.length ? (
              <details>
                <summary>More detail</summary>
                {[...new Set(TOOL_NOTES[s.id])].map((text, i) => (
                  <p key={i}>{text}</p>
                ))}
              </details>
            ) : null}
          </section>
        ))}
      </div>
      {!visible.length && <p role="status">No matching help topics.</p>}
      <p>
        <a href="mailto:admin@coopscorner.tech">Contact support</a>
      </p>
    </main>
  );
}

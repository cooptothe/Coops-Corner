"use client";
import Link from "next/link";
import Image from "next/image";
import { PersonalNav } from "./personal-nav";
import { UserMenu } from "./auth-provider";
import { ParlayToolbar } from "./parlay-builder";
import LabResearch from "./props-trends";
export default function LabPage({
  selectedBetId,
}: {
  selectedBetId: string | null;
}) {
  return (
    <main id="main" className="personal-workspace lab-page">
      <header className="personal-header page-header">
        <Link href="/positive_ev">
          <Image
            src="/assets/corner-logo.png"
            width={64}
            height={64}
            alt="Coop's Corner"
          />
        </Link>
        <div>
          <p className="eyebrow">RESEARCH YOUR NEXT PLAY</p>
          <h1>The Lab</h1>
          <p className="subtitle">
            Know the player. Read the matchup. Build your slip.
          </p>
        </div>
        <div className="page-actions">
          <Link className="button secondary" href="/props">
            Player props
          </Link>
          <UserMenu />
        </div>
      </header>
      <PersonalNav current="lab" />
      <div className="lab-intro">
        <p>
          Explore hit rates at the current line, recent performances, and news
          in one place.
        </p>
        <ParlayToolbar />
      </div>
      <LabResearch selectedBetId={selectedBetId} />
    </main>
  );
}

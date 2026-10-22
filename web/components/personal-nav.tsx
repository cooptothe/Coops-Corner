"use client";
import { useEffect, useRef } from "react";
import Link from "next/link";

export function PersonalNav({
  current,
}: {
  current: "tracker" | "account" | "lab";
}) {
  const nav = useRef<HTMLElement>(null);
  useEffect(() => {
    if (matchMedia("(max-width: 700px)").matches)
      nav.current
        ?.querySelector<HTMLElement>('[aria-current="page"]')
        ?.scrollIntoView({ block: "nearest", inline: "center" });
  }, [current]);
  return (
    <nav ref={nav} className="personal-nav" aria-label="Workspace">
      <Link href="/games">Schedule</Link>
      <Link href="/positive_ev">Positive EV</Link>
      <Link href="/props">Player props</Link>
      <Link href="/lab" aria-current={current === "lab" ? "page" : undefined}>
        The Lab
      </Link>
      <Link href="/arbitrage">Arbitrage</Link>
      <Link href="/middle">Middles</Link>
      <Link href="/promo">Promo converter</Link>
      <Link
        href="/tracker"
        aria-current={current === "tracker" ? "page" : undefined}
      >
        Tracker &amp; bankroll
      </Link>
      <Link
        href="/account"
        aria-current={current === "account" ? "page" : undefined}
      >
        Account
      </Link>
    </nav>
  );
}

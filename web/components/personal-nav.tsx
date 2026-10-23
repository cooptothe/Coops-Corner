"use client";
import { useEffect, useRef } from "react";
import { NavigationLinks } from "./navigation-links";

export function PersonalNav({
  current,
}: {
  current: "tracker" | "account" | "lab" | "help";
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
      <NavigationLinks current={current} />
    </nav>
  );
}

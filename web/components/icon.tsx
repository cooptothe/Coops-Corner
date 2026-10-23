import type { CSSProperties } from "react";
const paths = {
  help: "M9 9a3 3 0 016 0c0 2-3 2-3 4M12 17h.01M12 3a9 9 0 100 18 9 9 0 000-18",
  grid: "M4 4h6v6H4ZM14 4h6v6h-6ZM4 14h6v6H4ZM14 14h6v6h-6Z",
  account: "M4 21v-2a8 8 0 0116 0v2M12 3a4 4 0 100 8 4 4 0 000-8",
  close: "M6 6l12 12M6 18L18 6",
  check: "M5 12l4 4L19 6",
  play: "M8 5l11 7-11 7Z",
  pause: "M8 5v14M16 5v14",
  clock: "M12 8v4l3 2",
  trend: "M3 17l6-6 4 4 8-10M15 5h6v6",
  exchange: "M3 7h18l-4-4M21 17H3l4 4",
  middle: "M4 5l8 7-8 7V5ZM20 5l-8 7 8 7V5Z",
  player: "M8 20v-3a4 4 0 018 0v3M12 4a4 4 0 100 8 4 4 0 000-8",
  calendar: "M4 5h16v15H4ZM4 10h16M8 3v4M16 3v4",
  promo: "M3 12l9-9h8v8l-9 9ZM16 7h.01",
  lab: "M9 3h6M10 3v7l-6 9a1 1 0 001 2h14a1 1 0 001-2l-6-9V3M8 15h8",
  wallet: "M3 6h18v14H3ZM3 6l14-3v3M15 11h6v5h-6Z",
  external: "M14 3h7v7M21 3l-12 12M10 3H3v18h18v-7",
};
export function Icon({
  name,
  style,
}: {
  name: keyof typeof paths;
  style?: CSSProperties;
}) {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ verticalAlign: "middle", flexShrink: 0, ...style }}
    >
      {name === "clock" && <circle cx="12" cy="12" r="9" />}
      <path d={paths[name]} />
    </svg>
  );
}

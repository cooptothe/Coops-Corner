import Link from "next/link";
import { Icon } from "./icon";

export const APP_NAVIGATION = [
  { id: "positive_ev", label: "Positive EV", icon: "trend" },
  { id: "arbitrage", label: "Arbitrage", icon: "exchange" },
  { id: "middle", label: "Middles", icon: "middle" },
  { id: "props", label: "Player props", icon: "player" },
  { id: "games", label: "Schedule", icon: "calendar" },
  { id: "promo", label: "Promo converter", icon: "promo" },
  { id: "lab", label: "The Lab", icon: "lab" },
  { id: "tracker", label: "Tracker & bankroll", icon: "wallet" },
  { id: "account", label: "Account", icon: "account" },
  { id: "help", label: "Help & guide", icon: "help" },
] as const;

export function NavigationLinks({ current }: { current: string }) {
  return (
    <>
      {APP_NAVIGATION.map((item) => (
        <Link
          key={item.id}
          href={`/${item.id}`}
          className={current === item.id ? "active" : ""}
          aria-current={current === item.id ? "page" : undefined}
        >
          <span className="nav-icon">
            <Icon name={item.icon} />
          </span>
          {item.label}
        </Link>
      ))}
    </>
  );
}

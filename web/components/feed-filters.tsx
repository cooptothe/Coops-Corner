"use client";
import { useContext, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { LiveBetLinks } from "./bet-link";
import { useUiBoolean } from "./use-ui-boolean";

export function FeedFilters({
  children,
  active,
}: {
  children: ReactNode;
  active: boolean;
}) {
  const path = usePathname();
  const live = useContext(LiveBetLinks);
  const panel = useUiBoolean(
    `filters.${path}.${live ? "live" : "pregame"}`,
    () => !matchMedia("(max-width: 700px)").matches,
  );
  const open = panel.value;
  return (
    <aside className="feed-filter-shell" aria-label="Feed filters">
      <details
        className="feed-filter-panel"
        open={open}
        onToggle={(event) => {
          const next = event.currentTarget.open;
          if (panel.ready && next !== open) panel.setValue(next);
        }}
      >
        <summary>
          <span>
            Filters &amp; presets{" "}
            <small>{active ? "Customized" : "All results"}</small>
          </span>
          <span className="filter-toggle-label">
            {open ? "Hide filters" : "Show filters"}{" "}
            <span aria-hidden="true">⌄</span>
          </span>
        </summary>
        <div className="ev-filters">{children}</div>
      </details>
    </aside>
  );
}

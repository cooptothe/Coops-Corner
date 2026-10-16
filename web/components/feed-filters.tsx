"use client";
import { useEffect, useState, type ReactNode } from "react";

export function FeedFilters({
  children,
  active,
}: {
  children: ReactNode;
  active: boolean;
}) {
  const [open, setOpen] = useState(true);
  useEffect(() => {
    const media = matchMedia("(max-width: 700px)");
    const update = () => setOpen(!media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return (
    <aside className="feed-filter-shell" aria-label="Feed filters">
      <details
        className="feed-filter-panel"
        open={open}
        onToggle={(event) => setOpen(event.currentTarget.open)}
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

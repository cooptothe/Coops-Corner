"use client";
import { useEffect, useRef, useState } from "react";
import { QuoteAge } from "./quote-age";
export const shortBook = (name: string) =>
  name.replace("Demo ", "").replace("Reference ", "Ref ");

export function Age({ value }: { value: string }) {
  return <QuoteAge value={value} />;
}

export function CopyButton({ value, label }: { value: string; label: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      className="button secondary arb-copy"
      aria-label={`Copy ${label} stake`}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setDone(true);
          setTimeout(() => setDone(false), 1200);
        } catch {}
      }}
    >
      {done ? "Copied" : "Copy"}
    </button>
  );
}

export function Menu({
  title,
  items,
  off,
  setOff,
}: {
  title: string;
  items: [string, string][];
  off: Set<string>;
  setOff: (next: Set<string>) => void;
}) {
  const root = useRef<HTMLDetailsElement>(null);
  const [query, setQuery] = useState("");
  useEffect(() => {
    const close = (event: PointerEvent) => {
      if (root.current?.open && !root.current.contains(event.target as Node))
        root.current.open = false;
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, []);
  const choices = items.filter(([, label]) =>
    label.toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <details
      className="arb-menu"
      ref={root}
      onKeyDown={(event) => {
        if (event.key === "Escape" && root.current) {
          root.current.open = false;
          root.current.querySelector("summary")?.focus();
        }
      }}
    >
      <summary>
        {title} ({items.filter(([id]) => !off.has(id)).length}/{items.length})
      </summary>
      <div className="arb-menu-pop">
        <div>
          <button
            type="button"
            className="link-button"
            onClick={() => setOff(new Set())}
          >
            Select all
          </button>{" "}
          <button
            type="button"
            className="link-button"
            onClick={() => setOff(new Set(items.map(([id]) => id)))}
          >
            Clear all
          </button>
        </div>
        {items.length > 6 && (
          <input
            className="menu-search"
            type="search"
            placeholder={`Search ${title.toLowerCase()}`}
            aria-label={`Search ${title.toLowerCase()}`}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        )}
        {choices.map(([id, label]) => (
          <label key={id}>
            <input
              type="checkbox"
              checked={!off.has(id)}
              onChange={() => {
                const next = new Set(off);
                if (!next.delete(id)) next.add(id);
                setOff(next);
              }}
            />
            {label}
          </label>
        ))}
        {items.length === 0 && <small>None yet.</small>}
        {!!items.length && !choices.length && (
          <small>No matches. Try another name.</small>
        )}
      </div>
    </details>
  );
}

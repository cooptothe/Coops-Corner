"use client";
import "../app/live-feed.css";
export function LiveSwitch({
  enabled,
  onChange,
}: {
  enabled: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <div className="live-mode-control">
      <span className={!enabled ? "selected" : ""}>Pregame</span>
      <button
        type="button"
        className="live-mode-switch"
        role="switch"
        aria-label="Live mode · Premium"
        aria-checked={enabled}
        onClick={() => onChange(!enabled)}
      >
        <span />
      </button>
      <span className={enabled ? "selected" : ""}>
        Live <small>Premium</small>
      </span>
    </div>
  );
}

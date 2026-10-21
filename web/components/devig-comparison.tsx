"use client";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { american, divDecimal, percent } from "../../frontend/format.mjs";

export interface DevigResult {
  method: string;
  probability: string;
  ev: string;
}
export const names: Record<string, string> = {
  multiplicative: "Multiplicative",
  additive: "Additive",
  power: "Power",
  shin: "Shin",
  worst_case: "Worst case",
};

function ComparisonDialog({
  rows,
  close,
}: {
  rows: DevigResult[];
  close: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      onClose={close}
      aria-label="Compare devig methods"
      onClick={(e) => e.stopPropagation()}
      style={{
        width: "min(34rem, calc(100vw - 2rem))",
        maxHeight: "80dvh",
        overflow: "auto",
        background: "#1e191d",
        color: "#fafafa",
        border: "1px solid #68505c",
        borderRadius: "12px",
        padding: "20px",
      }}
    >
      <button
        type="button"
        onClick={close}
        style={{ float: "right" }}
        aria-label="Close devig comparison"
      >
        Close
      </button>
      <h3>Compare devig methods</h3>
      <p>
        Same reference books and weights. The feed uses your selected method.
        One-sided estimates keep their separate margin model.
      </p>
      <div style={{ overflowX: "auto" }}>
        <table
          style={{
            width: "100%",
            textAlign: "left",
            fontVariantNumeric: "tabular-nums",
          }}
        >
          <thead>
            <tr>
              <th scope="col">Method</th>
              <th scope="col">Selection chance</th>
              <th scope="col">Fair odds</th>
              <th scope="col">EV</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.method}>
                <th scope="row">{names[row.method] ?? row.method}</th>
                <td>{percent(row.probability)}</td>
                <td>
                  {Number(row.probability) > 0 && Number(row.probability) < 1
                    ? american(divDecimal("1", row.probability))
                    : "—"}
                </td>
                <td>{percent(row.ev)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p>
        <small>
          EV includes modeled fees. These are margin assumptions, not measured
          win rates or confidence bounds. Push-capable markets are conditional
          on decisive settlement. Worst case uses the lowest EV across valid
          methods; its outcome probabilities need not total 100%. An unavailable
          method is omitted.
        </small>
      </p>
    </dialog>
  );
}

export function DevigComparison({ rows }: { rows?: DevigResult[] | null }) {
  const [open, setOpen] = useState(false);
  if (!rows?.length) return null;
  return (
    <>
      <button
        type="button"
        className="button secondary"
        style={{
          padding: "4px 8px",
          fontSize: "0.75rem",
          minHeight: "32px",
          maxWidth: "100%",
          whiteSpace: "normal",
        }}
        onClick={(e) => {
          e.stopPropagation();
          setOpen(true);
        }}
      >
        Compare devig
      </button>
      {open &&
        createPortal(
          <ComparisonDialog rows={rows} close={() => setOpen(false)} />,
          document.body,
        )}
    </>
  );
}

export function DevigSelector({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="field">
      <span>DEVIG METHOD</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="current">App default</option>
        {Object.entries(names).map(([key, label]) => (
          <option key={key} value={key}>
            {label}
          </option>
        ))}
      </select>
      <small>
        Changes estimates and EV filters; reference books stay fixed.
        Unavailable methods are excluded.
      </small>
    </label>
  );
}

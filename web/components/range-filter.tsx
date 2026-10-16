"use client";
import { useId, type CSSProperties } from "react";

export function RangeFilter({
  label,
  value,
  onChange,
  max = 10,
  step = 0.25,
  unit = "%",
  unlimited = false,
  help,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  max?: number;
  step?: number;
  unit?: string;
  unlimited?: boolean;
  help?: string;
}) {
  const id = useId();
  const upper = Math.max(max, Math.ceil((Number(value) || 0) / step) * step);
  const end = upper + (unlimited ? step : 0);
  const position = value === "" && unlimited ? end : Number(value) || 0;
  const display =
    value === "" && unlimited ? "No limit" : `${value || "0"}${unit}`;
  return (
    <div className="field range-field">
      <div className="range-heading">
        <label htmlFor={id}>{label}</label>
        <output htmlFor={id}>{display}</output>
      </div>
      <input
        id={id}
        type="range"
        min="0"
        max={end}
        step={step}
        value={position}
        aria-valuetext={display}
        aria-describedby={help ? `${id}-help` : undefined}
        style={
          { "--range-progress": `${(position / end) * 100}%` } as CSSProperties
        }
        onChange={(e) =>
          onChange(
            unlimited && Number(e.target.value) >= end ? "" : e.target.value,
          )
        }
      />
      <div className="range-scale" aria-hidden="true">
        <span>0{unit}</span>
        <span>{unlimited ? "No limit" : `${upper}${unit}`}</span>
      </div>
      {help && (
        <details className="range-help">
          <summary>About market width</summary>
          <small id={`${id}-help`}>{help}</small>
        </details>
      )}
    </div>
  );
}

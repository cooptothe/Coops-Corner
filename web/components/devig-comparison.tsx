"use client";
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
    </label>
  );
}

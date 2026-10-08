"use client";
import { useMemo, useState } from "react";
import { signedDollars } from "../lib/tracker-math";

export interface ChartSeries {
  label: string;
  color: string;
  dashed?: boolean;
  // One value (in cents) per day, aligned with `days`.
  values: number[];
}

const W = 720;
const H = 220;
const PAD = { l: 64, r: 14, t: 12, b: 26 };

const compact = (cents: number) => {
  const d = Math.abs(cents / 100);
  const text =
    d >= 1000 ? `${(d / 1000).toFixed(d >= 10000 ? 0 : 1)}k` : d.toFixed(0);
  return `${cents < 0 ? "-" : ""}$${text}`;
};

// A dependency-free SVG line chart. Hovering (or focusing and using the arrow keys) reads the values for a day.
export function LineChart({
  days,
  series,
  label,
}: {
  days: string[];
  series: ChartSeries[];
  label: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const geometry = useMemo(() => {
    const all = series.flatMap((s) => s.values);
    if (!all.length) return null;
    let lo = Math.min(0, ...all);
    let hi = Math.max(0, ...all);
    if (hi === lo) hi = lo + 100;
    const pad = (hi - lo) * 0.06;
    lo -= lo < 0 ? pad : 0;
    hi += pad;
    const x = (i: number) =>
      PAD.l +
      (days.length < 2 ? 0 : (i / (days.length - 1)) * (W - PAD.l - PAD.r));
    const y = (v: number) =>
      PAD.t + (1 - (v - lo) / (hi - lo)) * (H - PAD.t - PAD.b);
    const ticks = [0, 1, 2, 3].map((n) => lo + ((hi - lo) * n) / 3);
    return { x, y, lo, hi, ticks };
  }, [series, days]);
  if (!geometry || !days.length)
    return <p className="trk-empty">Not enough history yet.</p>;
  const { x, y, ticks } = geometry;
  const at = hover ?? days.length - 1;
  const move = (clientX: number, box: DOMRect) => {
    const px = ((clientX - box.left) / box.width) * W;
    const i = Math.round(
      ((px - PAD.l) / (W - PAD.l - PAD.r)) * (days.length - 1),
    );
    setHover(Math.max(0, Math.min(days.length - 1, i)));
  };
  return (
    <figure className="trk-chart">
      <figcaption>
        <strong>{days[at]}</strong>
        {series.map((s) => (
          <span key={s.label}>
            <i style={{ background: s.color }} aria-hidden="true" />
            {s.label} <b>{signedDollars(s.values[at] ?? 0)}</b>
          </span>
        ))}
      </figcaption>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={label}
        tabIndex={0}
        onMouseMove={(e) =>
          move(e.clientX, e.currentTarget.getBoundingClientRect())
        }
        onMouseLeave={() => setHover(null)}
        onKeyDown={(e) => {
          if (e.key === "ArrowLeft") setHover(Math.max(0, at - 1));
          else if (e.key === "ArrowRight")
            setHover(Math.min(days.length - 1, at + 1));
          else if (e.key === "Escape") setHover(null);
        }}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={PAD.l}
              x2={W - PAD.r}
              y1={y(t)}
              y2={y(t)}
              className="trk-grid"
            />
            <text
              x={PAD.l - 8}
              y={y(t) + 4}
              textAnchor="end"
              className="trk-axis"
            >
              {compact(t)}
            </text>
          </g>
        ))}
        <line
          x1={PAD.l}
          x2={W - PAD.r}
          y1={y(0)}
          y2={y(0)}
          className="trk-zero"
        />
        {[0, Math.floor((days.length - 1) / 2), days.length - 1]
          .filter((v, i, a) => a.indexOf(v) === i)
          .map((i) => (
            <text
              key={i}
              x={x(i)}
              y={H - 6}
              textAnchor={
                i === 0 ? "start" : i === days.length - 1 ? "end" : "middle"
              }
              className="trk-axis"
            >
              {days[i].slice(5)}
            </text>
          ))}
        {series.map((s) => (
          <path
            key={s.label}
            d={s.values
              .map(
                (v, i) =>
                  `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`,
              )
              .join("")}
            fill="none"
            stroke={s.color}
            strokeWidth={2}
            strokeDasharray={s.dashed ? "5 4" : undefined}
            strokeLinejoin="round"
          />
        ))}
        <line
          x1={x(at)}
          x2={x(at)}
          y1={PAD.t}
          y2={H - PAD.b}
          className="trk-cursor"
        />
        {series.map((s) => (
          <circle
            key={s.label}
            cx={x(at)}
            cy={y(s.values[at] ?? 0)}
            r={3.5}
            fill={s.color}
          />
        ))}
      </svg>
    </figure>
  );
}

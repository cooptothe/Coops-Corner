import { RangeFilter } from "./range-filter";

export function EvFilterLimits({
  maxEv,
  maxWidth,
  setMaxEv,
  setMaxWidth,
}: {
  maxEv: string;
  maxWidth: string;
  setMaxEv: (value: string) => void;
  setMaxWidth: (value: string) => void;
}) {
  return (
    <>
      <RangeFilter
        label="Maximum EV"
        value={maxEv}
        onChange={setMaxEv}
        max={50}
        unlimited
      />

      <RangeFilter
        label="Max. market width"
        value={maxWidth}
        onChange={setMaxWidth}
        max={200}
        step={1}
        unit="¢"
        unlimited

        help="Lower widths mean tighter reference prices. Bets with unknown width are hidden when a limit is set."
      />
    </>
  );
}

export function feedLayout(
  ids: readonly string[],
  sizes: ReadonlyMap<string, number>,
  estimate: number,
  scroll: number,
  viewport: number,
  overscan = 4,
) {
  const offsets = [0];
  for (const id of ids)
    offsets.push(offsets[offsets.length - 1] + (sizes.get(id) ?? estimate));
  const at = (y: number) => {
    let lo = 0,
      hi = ids.length;
    while (lo < hi) {
      const m = (lo + hi) >>> 1;
      if (offsets[m + 1] <= y) lo = m + 1;
      else hi = m;
    }
    return lo;
  };
  return {
    offsets,
    total: offsets[offsets.length - 1],
    first: Math.max(0, at(scroll) - overscan),
    last: Math.min(ids.length, at(scroll + viewport) + 1 + overscan),
  };
}

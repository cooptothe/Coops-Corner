// Rebuild the height index only when rows, measurements or layout change.
export function feedOffsets(
  ids: readonly string[],
  sizes: ReadonlyMap<string, number>,
  estimate: number,
) {
  const offsets = [0];
  for (const id of ids)
    offsets.push(offsets[offsets.length - 1] + (sizes.get(id) ?? estimate));
  return offsets;
}

// Scrolling searches an existing height index in O(log n), without walking every row.
export function feedWindow(
  offsets: number[],
  scroll: number,
  viewport: number,
  overscan = 4,
) {
  const at = (y: number) => {
    let lo = 0,
      hi = offsets.length - 1;
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
    last: Math.min(offsets.length - 1, at(scroll + viewport) + 1 + overscan),
  };
}

export function feedLayout(
  ids: readonly string[],
  sizes: ReadonlyMap<string, number>,
  estimate: number,
  scroll: number,
  viewport: number,
  overscan = 4,
) {
  return feedWindow(
    feedOffsets(ids, sizes, estimate),
    scroll,
    viewport,
    overscan,
  );
}

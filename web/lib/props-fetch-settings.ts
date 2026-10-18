export function restoredFetchMarkets(
  saved: string[] | null,
  catalog: { key: string; default: boolean }[],
) {
  return saved === null
    ? catalog.filter((m) => m.default).map((m) => m.key)
    : saved.filter((key) => catalog.some((m) => m.key === key));
}

// Preserve custom choices; one click adds only documented alternatives to chosen stats.
export function withAlternateMarkets(
  selected: string[],
  catalog: { key: string }[],
) {
  const available = new Set(catalog.map((m) => m.key));
  return [
    ...new Set([
      ...selected,
      ...selected
        .map((key) => `${key}_alternate`)
        .filter((key) => available.has(key)),
    ]),
  ];
}

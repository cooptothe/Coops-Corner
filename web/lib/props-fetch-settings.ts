export function restoredFetchMarkets(
  saved: string[] | null,
  catalog: { key: string; default: boolean }[],
) {
  return saved === null
    ? catalog.filter((m) => m.default).map((m) => m.key)
    : saved.filter((key) => catalog.some((m) => m.key === key));
}

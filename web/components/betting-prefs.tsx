"use client";
import { useCallback, useSyncExternalStore } from "react";
import { validState } from "../lib/bet-links";
import { useSettingsStore } from "./settings-provider";

// Betting preferences of the signed-in account. For now: the US state used to open BetMGM and BetRivers links.
export function useBettingPrefs() {
  const store = useSettingsStore();
  const saved = useSyncExternalStore(
    store.subscribe,
    () => store.get("account"),
    () => store.get("account"),
  );
  const state = validState(saved?.state);
  const setState = useCallback(
    (next: string) =>
      store.put("account", {
        ...store.get("account"),
        state: validState(next),
      }),
    [store],
  );
  return { state, setState };
}

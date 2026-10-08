"use client";
import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import {
  deletePresetRequest,
  loadSettings,
  savePresetRequest,
  saveToolSettings,
} from "../lib/settings-api";
import { SettingsStore } from "../lib/settings-store";
import { Splash } from "./auth-provider";

export const StoreContext = createContext<SettingsStore | null>(null);

export function useSettingsStore(): SettingsStore {
  const store = useContext(StoreContext);
  if (!store) throw new Error("useSettingsStore needs a SettingsProvider");
  return store;
}

const api = {
  save: saveToolSettings,
  savePreset: savePresetRequest,
  deletePreset: deletePresetRequest,
};

// Loads the signed-in account's saved settings once, then keeps them in memory for every tool page.
export function SettingsProvider({ children }: { children: ReactNode }) {
  const [store, setStore] = useState<SettingsStore | null>(null);

  useEffect(() => {
    let live = true;
    loadSettings().then(
      (data) => live && setStore(new SettingsStore(data, api)),
      () =>
        live &&
        setStore(
          new SettingsStore(
            null,
            api,
            "Your saved settings could not be loaded, so changes here are not being saved.",
          ),
        ),
    );
    return () => {
      live = false;
    };
  }, []);

  // Send any change still waiting when the tab is hidden or closed.
  useEffect(() => {
    if (!store) return;
    const hide = () => store.flush(true);
    const onVisibility = () =>
      document.visibilityState === "hidden" && store.flush(true);
    window.addEventListener("pagehide", hide);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("pagehide", hide);
      document.removeEventListener("visibilitychange", onVisibility);
      store.flush(true);
    };
  }, [store]);

  if (!store) return <Splash />;
  return (
    <StoreContext.Provider value={store}>{children}</StoreContext.Provider>
  );
}

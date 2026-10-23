"use client";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "./auth-provider";
import { readUiBoolean, saveUiBoolean } from "../lib/ui-preferences";

// Restore after hydration, isolate accounts/routes, and never overwrite saved state on mount.
export function useUiBoolean(key: string, fallback: boolean | (() => boolean)) {
  const { user } = useAuth();
  const scope = `${user?.id ?? "signed-out"}|${key}`;
  const defaults = useRef(fallback);
  defaults.current = fallback;
  const [saved, setSaved] = useState<{ scope: string; value: boolean } | null>(
    null,
  );
  useEffect(() => {
    const initial =
      typeof defaults.current === "function"
        ? defaults.current()
        : defaults.current;
    setSaved({ scope, value: readUiBoolean(key, initial) });
  }, [scope, key]);
  return {
    ready: saved?.scope === scope,
    value: saved?.scope === scope ? saved.value : false,
    setValue(value: boolean) {
      setSaved({ scope, value });
      saveUiBoolean(key, value);
    },
  };
}

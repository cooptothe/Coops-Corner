"use client";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { canon, type SettingsStore } from "../lib/settings-store";
import type { Preset, Settings } from "../lib/settings-api";
import { useSettingsStore } from "./settings-provider";

// A tool's filter state, kept for the signed-in account:
//  - restored from the account's saved settings when the page opens (so leaving and coming back changes nothing),
//  - saved a moment after every change,
//  - with named presets and a reset to the tool's defaults.
// The page keeps its own useState values; it only describes them as `snapshot` and knows how to `apply` them back.
export interface ToolSettingsOptions<T extends Settings> {
  tool: string;
  defaults: T;
  snapshot: T;
  // Receives a complete settings object (defaults filled in) and must validate every value it uses.
  apply: (settings: T) => void;
  // Settings kept in this browser before they moved to the account; used once, if nothing is saved yet.
  legacy?: () => Partial<T> | null;
  presets?: boolean;
}

export interface ToolSettingsControls {
  presets: Preset[];
  active: Preset | null;
  // The page differs from the selected preset.
  modified: boolean;
  atDefaults: boolean;
  syncError: string | null;
  showPresets: boolean;
  choose: (id: string) => void;
  savePreset: (name: string) => Promise<void>;
  updateActive: () => Promise<void>;
  deleteActive: () => Promise<void>;
  reset: () => void;
}

const EMPTY: Preset[] = [];

export function useToolSettings<T extends Settings>(
  options: ToolSettingsOptions<T>,
): ToolSettingsControls {
  const { tool, defaults, snapshot, presets: withPresets = true } = options;
  const store: SettingsStore = useSettingsStore();
  const [ready, setReady] = useState(false);
  const [activeId, setActiveId] = useState<string | null>(() =>
    store.activePreset(tool),
  );
  const latest = useRef(options);
  latest.current = options;

  // Restore once. Reading from the in-memory store makes this instant, with no flash of default filters.
  useEffect(() => {
    const { defaults: d, apply, legacy } = latest.current;
    let saved: Partial<T> | undefined = store.get(tool) as
      Partial<T> | undefined;
    if (!saved && legacy) {
      try {
        saved = legacy() ?? undefined;
      } catch {
        saved = undefined;
      }
    }
    if (saved) apply({ ...d, ...saved });
    setReady(true);
  }, [store, tool]);

  const key = canon(snapshot);
  const defaultKey = canon(defaults);
  useEffect(() => {
    if (!ready) return;
    // Nothing is stored until the user changes something from the defaults.
    if (!store.get(tool) && key === defaultKey) return;
    store.put(tool, JSON.parse(key) as Settings);
  }, [ready, store, tool, key, defaultKey]);

  const list = useSyncExternalStore(
    store.subscribe,
    () => store.presets(tool),
    () => EMPTY,
  );
  const syncError = useSyncExternalStore(
    store.subscribe,
    store.syncError,
    () => null,
  );

  const matches = (p: Preset) => canon({ ...defaults, ...p.settings }) === key;
  const active =
    list.find((p) => p.id === activeId) ?? list.find(matches) ?? null;
  const modified = !!active && !matches(active);
  const atDefaults = key === defaultKey;

  const remember = useCallback(
    (id: string | null) => {
      store.setActivePreset(tool, id);
      setActiveId(id);
    },
    [store, tool],
  );
  const choose = useCallback(
    (id: string) => {
      const preset = store.presets(tool).find((p) => p.id === id);
      if (!preset) return remember(null);
      const { defaults: d, apply } = latest.current;
      apply({ ...d, ...preset.settings } as T);
      remember(id);
    },
    [store, tool, remember],
  );
  const savePreset = useCallback(
    async (name: string) => {
      const saved = await store.savePreset(
        tool,
        name,
        JSON.parse(canon(latest.current.snapshot)) as Settings,
      );
      remember(saved.id);
    },
    [store, tool, remember],
  );
  const updateActive = useCallback(async () => {
    const current = store.presets(tool).find((p) => p.id === activeId);
    if (current) await savePreset(current.name);
  }, [store, tool, activeId, savePreset]);
  const deleteActive = useCallback(async () => {
    const current = store.presets(tool).find((p) => p.id === activeId);
    if (!current) return;
    await store.deletePreset(tool, current.id);
    remember(null);
  }, [store, tool, activeId, remember]);
  const reset = useCallback(() => {
    latest.current.apply({ ...latest.current.defaults });
    remember(null);
  }, [remember]);

  return {
    presets: list,
    active,
    modified,
    atDefaults,
    syncError,
    showPresets: withPresets,
    choose,
    savePreset,
    updateActive,
    deleteActive,
    reset,
  };
}

// The presets row shown in every tool's filter area.
export function SettingsBar({ controls }: { controls: ToolSettingsControls }) {
  const c = controls;
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  const run = async (work: () => Promise<void>, done: string) => {
    setBusy(true);
    setError("");
    setStatus("");
    try {
      await work();
      setStatus(done);
    } catch (e) {
      setError(e instanceof Error ? e.message : "That did not work.");
    } finally {
      setBusy(false);
    }
  };
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return setError("Give the preset a name.");
    run(async () => {
      await c.savePreset(trimmed);
      setNaming(false);
      setName("");
    }, `Saved “${trimmed}”.`);
  };

  return (
    <div className="settings-bar" role="group" aria-label="Saved settings">
      {c.showPresets && (
        <label className="field settings-select">
          <span>PRESET</span>
          <select
            value={c.active?.id ?? ""}
            onChange={(e) => {
              setError("");
              setStatus("");
              c.choose(e.target.value);
            }}
          >
            <option value="">
              {c.presets.length ? "Current (not a preset)" : "No presets yet"}
            </option>
            {c.presets.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
      )}
      <div className="settings-actions">
        {c.showPresets &&
          (naming ? (
            <form className="settings-name" onSubmit={submit}>
              <input
                value={name}
                maxLength={40}
                placeholder="Preset name"
                aria-label="Preset name"
                autoFocus
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => e.key === "Escape" && setNaming(false)}
              />
              <button className="button" type="submit" disabled={busy}>
                Save
              </button>
              <button
                className="button secondary"
                type="button"
                onClick={() => {
                  setNaming(false);
                  setError("");
                }}
              >
                Cancel
              </button>
            </form>
          ) : (
            <>
              <button
                className="button secondary"
                type="button"
                onClick={() => {
                  setNaming(true);
                  setStatus("");
                }}
              >
                Save as preset…
              </button>
              {c.active && c.modified && (
                <button
                  className="button secondary"
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    run(c.updateActive, `Updated “${c.active!.name}”.`)
                  }
                >
                  Update “{c.active.name}”
                </button>
              )}
              {c.active && (
                <button
                  className="button secondary"
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    if (
                      window.confirm(`Delete the preset “${c.active!.name}”?`)
                    )
                      run(c.deleteActive, "Preset deleted.");
                  }}
                >
                  Delete
                </button>
              )}
            </>
          ))}
        <button
          className="button secondary"
          type="button"
          disabled={c.atDefaults}
          onClick={() => {
            setError("");
            setStatus("Reset to defaults.");
            c.reset();
          }}
        >
          Reset to defaults
        </button>
      </div>
      <div className="settings-notes" aria-live="polite">
        {c.modified && c.active && !error && (
          <small>Changed since “{c.active.name}” was saved.</small>
        )}
        {status && !error && <small>{status}</small>}
        {error && (
          <small role="alert" className="settings-error">
            {error}
          </small>
        )}
        {c.syncError && (
          <small role="alert" className="settings-error">
            {c.syncError}
          </small>
        )}
      </div>
    </div>
  );
}

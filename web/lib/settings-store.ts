// The in-memory home of one account's saved tool settings and presets. It is plain TypeScript (no React) so
// it can be tested on its own: the page reads from it instantly (so navigating between tools never loses
// state) and it saves to the server in the background, a moment after the last change.
import type { Preset, Settings, SettingsData } from "./settings-api";

export interface SettingsApi {
  save: (
    tool: string,
    settings: Settings,
    keepalive?: boolean,
  ) => Promise<unknown>;
  savePreset: (
    tool: string,
    name: string,
    settings: Settings,
  ) => Promise<Preset>;
  deletePreset: (id: string) => Promise<unknown>;
}

// Stable text for a value: object keys sorted, so equal settings always compare equal.
export function canon(value: unknown): string {
  return JSON.stringify(value, (_key, v) =>
    v && typeof v === "object" && !Array.isArray(v)
      ? Object.fromEntries(
          Object.entries(v as Record<string, unknown>).sort(([a], [b]) =>
            a < b ? -1 : a > b ? 1 : 0,
          ),
        )
      : v,
  );
}

const NO_PRESETS: Preset[] = [];
const SAVE_DELAY = 600;

export class SettingsStore {
  private tools: Record<string, Settings>;
  private lists: Record<string, Preset[]>;
  private active = new Map<string, string | null>();
  private listeners = new Set<() => void>();
  private timers = new Map<string, ReturnType<typeof setTimeout>>();
  private pending = new Map<string, Settings>();
  private failure: string | null;

  constructor(
    initial: SettingsData | null,
    private api: SettingsApi,
    loadError: string | null = null,
  ) {
    this.tools = { ...(initial?.tools ?? {}) };
    this.lists = { ...(initial?.presets ?? {}) };
    this.failure = loadError;
  }

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  private emit() {
    for (const l of [...this.listeners]) l();
  }

  get(tool: string): Settings | undefined {
    return this.tools[tool];
  }
  presets = (tool: string): Preset[] => this.lists[tool] ?? NO_PRESETS;
  // The message to show when the last save or load failed; null while everything is synced.
  syncError = (): string | null => this.failure;
  activePreset(tool: string): string | null {
    return this.active.get(tool) ?? null;
  }
  setActivePreset(tool: string, id: string | null) {
    this.active.set(tool, id);
  }

  put(tool: string, settings: Settings) {
    if (this.tools[tool] && canon(this.tools[tool]) === canon(settings)) return;
    this.tools[tool] = settings;
    this.pending.set(tool, settings);
    clearTimeout(this.timers.get(tool));
    this.timers.set(
      tool,
      setTimeout(() => void this.send(tool), SAVE_DELAY),
    );
  }

  private async send(tool: string, keepalive = false) {
    clearTimeout(this.timers.get(tool));
    this.timers.delete(tool);
    const settings = this.pending.get(tool);
    if (!settings) return;
    this.pending.delete(tool);
    try {
      await this.api.save(tool, settings, keepalive);
      if (this.failure) {
        this.failure = null;
        this.emit();
      }
    } catch (e) {
      // Keep the value so the next change (or flush) tries again.
      if (!this.pending.has(tool)) this.pending.set(tool, settings);
      this.failure =
        e instanceof Error ? e.message : "Your settings could not be saved.";
      this.emit();
    }
  }

  // Sends anything still waiting, e.g. when the tab is being closed.
  flush(keepalive = false) {
    for (const tool of [...this.pending.keys()])
      void this.send(tool, keepalive);
  }

  async savePreset(
    tool: string,
    name: string,
    settings: Settings,
  ): Promise<Preset> {
    const preset = await this.api.savePreset(tool, name, settings);
    const others = this.presets(tool).filter((p) => p.id !== preset.id);
    this.lists = {
      ...this.lists,
      [tool]: [...others, preset].sort((a, b) =>
        a.name.toLowerCase().localeCompare(b.name.toLowerCase()),
      ),
    };
    this.emit();
    return preset;
  }

  async deletePreset(tool: string, id: string) {
    await this.api.deletePreset(id);
    this.lists = {
      ...this.lists,
      [tool]: this.presets(tool).filter((p) => p.id !== id),
    };
    if (this.active.get(tool) === id) this.active.set(tool, null);
    this.emit();
  }
}

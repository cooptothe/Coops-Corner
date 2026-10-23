import { userStorage } from "./user-storage";

export function readUiBoolean(key: string, fallback: boolean): boolean {
  try {
    const saved = userStorage.getItem(`corner.ui.${key}`);
    return saved === "true" ? true : saved === "false" ? false : fallback;
  } catch {
    return fallback;
  }
}
export function saveUiBoolean(key: string, value: boolean): void {
  try {
    userStorage.setItem(`corner.ui.${key}`, String(value));
  } catch {}
}

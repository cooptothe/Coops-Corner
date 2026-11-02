import { userStorage, userTabStorage } from "./user-storage";

export function readUiBoolean(key: string, fallback: boolean): boolean {
  try {
    const saved =
      userTabStorage.getItem(`corner.ui.${key}`) ??
      userStorage.getItem(`corner.ui.${key}`);
    const value =
      saved === "true" ? true : saved === "false" ? false : fallback;
    userTabStorage.setItem(`corner.ui.${key}`, String(value));
    return value;
  } catch {
    return fallback;
  }
}
export function saveUiBoolean(key: string, value: boolean): void {
  try {
    userTabStorage.setItem(`corner.ui.${key}`, String(value));
    userStorage.setItem(`corner.ui.${key}`, String(value));
  } catch {}
}

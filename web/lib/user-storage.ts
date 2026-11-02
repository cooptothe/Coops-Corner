// Browser-side preferences (saved filters, bankroll box, Kelly multiplier, league picker) belong to the signed-in
// account, so two people sharing a browser never see or overwrite each other's settings.
let owner: string | null = null;
const ownerListeners = new Set<() => void>();
export function subscribeStorageOwner(listener: () => void) {
  ownerListeners.add(listener);
  return () => {
    ownerListeners.delete(listener);
  };
}

const PREFIX = "corner.u.";

export function setStorageOwner(userId: string | null): void {
  if (owner === userId) return;
  owner = userId;
  ownerListeners.forEach((listener) => listener());
}

const scoped = (key: string) => `${PREFIX}${owner}.${key}`;

function store(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

export const userStorage = {
  // Settings saved before accounts existed sit under the bare key. Whoever reads one first adopts it
  // (it is moved, not copied), so it can never be handed to a second person.
  getItem(key: string): string | null {
    const s = store();
    if (!s || !owner) return null;
    const mine = s.getItem(scoped(key));
    if (mine !== null) return mine;
    const legacy = s.getItem(key);
    if (legacy === null) return null;
    s.setItem(scoped(key), legacy);
    s.removeItem(key);
    return legacy;
  },
  setItem(key: string, value: string): void {
    const s = store();
    if (s && owner) s.setItem(scoped(key), value);
  },
  removeItem(key: string): void {
    const s = store();
    if (s && owner) s.removeItem(scoped(key));
  },
};

// sessionStorage is copied on tab duplication, then evolves independently.
// Scope by account as well, so switching accounts cannot expose another setup.
export const userTabStorage = {
  getItem(key: string): string | null {
    try {
      return owner && typeof sessionStorage !== "undefined"
        ? sessionStorage.getItem(scoped(key))
        : null;
    } catch {
      return null;
    }
  },
  setItem(key: string, value: string): void {
    try {
      if (owner && typeof sessionStorage !== "undefined")
        sessionStorage.setItem(scoped(key), value);
    } catch {}
  },
};

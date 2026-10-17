import type { User } from "./auth-api";

export function needsMembershipAccount(
  user: User | null,
  now = Date.now(),
): boolean {
  const access = user?.membership;
  return Boolean(
    access?.enforced &&
    (!access.allowed ||
      (access.expires_at !== null && now >= access.expires_at * 1000)),
  );
}

export function membershipRouteAllowed(pathname: string | null): boolean {
  return (
    pathname === "/account" || pathname === "/tracker" || pathname === "/login"
  );
}

// One account check for simultaneous feed failures. Invalidated results cannot
// restore a previous identity after logout, login or component cleanup.
export class AccountRecheck {
  private generation = 0;
  private pending: Promise<void> | null = null;
  constructor(
    private load: () => Promise<User | null>,
    private accept: (user: User | null) => void,
    private unavailable: () => void,
  ) {}
  invalidate() {
    this.generation++;
    this.pending = null;
  }
  check(): Promise<void> {
    if (this.pending) return this.pending;
    const generation = this.generation;
    const task = this.load()
      .then(
        (user) => {
          if (generation === this.generation) this.accept(user);
        },
        () => {
          if (generation === this.generation) this.unavailable();
        },
      )
      .finally(() => {
        if (this.pending === task) this.pending = null;
      });
    this.pending = task;
    return task;
  }
}

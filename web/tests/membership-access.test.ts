import assert from "node:assert/strict";
import { test } from "node:test";
import {
  AccountRecheck,
  membershipRouteAllowed,
  needsMembershipAccount,
} from "../lib/membership-access";
import type { User } from "../lib/auth-api";
const member: User = {
  id: "alice",
  username: "Alice",
  membership: {
    state: "trial",
    allowed: true,
    enforced: true,
    expires_at: 2000,
  },
};

test("known deadline blocks exactly at expiry and preserves recovery routes", () => {
  assert.equal(needsMembershipAccount(member, 1999999), false);
  assert.equal(needsMembershipAccount(member, 2000000), true);
  assert.equal(
    needsMembershipAccount(
      { ...member, membership: { ...member.membership!, allowed: false } },
      0,
    ),
    true,
  );
  assert.equal(
    needsMembershipAccount({ id: "local", username: "Local" }),
    false,
  );
  assert.equal(
    needsMembershipAccount(
      { ...member, membership: { ...member.membership!, enforced: false } },
      3000000,
    ),
    false,
  );
  for (const route of ["/account", "/tracker", "/login"])
    assert.equal(membershipRouteAllowed(route), true);
  for (const route of [
    "/",
    "/lab",
    "/positive_ev",
    "/tracker-other",
    "/account/unknown",
    null,
  ])
    assert.equal(membershipRouteAllowed(route), false);
});

test("simultaneous feed failures share an account check and preserve an expired login", async () => {
  let calls = 0;
  let finish!: (user: User | null) => void;
  const accepted: (User | null)[] = [];
  const check = new AccountRecheck(
    () => {
      calls++;
      return new Promise((resolve) => (finish = resolve));
    },
    (user) => accepted.push(user),
    () => assert.fail("unexpected outage"),
  );
  const one = check.check();
  const two = check.check();
  assert.equal(one, two);
  assert.equal(calls, 1);
  finish({
    ...member,
    membership: { ...member.membership!, state: "expired", allowed: false },
  });
  await one;
  assert.equal(accepted[0]?.id, "alice");
  assert.equal(accepted[0]?.membership?.allowed, false);
});

test("logout or identity change invalidates in-flight results and allows a fresh check", async () => {
  const completions: ((user: User | null) => void)[] = [];
  const accepted: (User | null)[] = [];
  const check = new AccountRecheck(
    () => new Promise((resolve) => completions.push(resolve)),
    (user) => accepted.push(user),
    () => assert.fail("unexpected outage"),
  );
  const old = check.check();
  check.invalidate();
  const fresh = check.check();
  completions[0](member);
  await old;
  assert.equal(accepted.length, 0);
  completions[1](null);
  await fresh;
  assert.deepEqual(accepted, [null]);
});

test("an unavailable authentication service is not interpreted as a lost login", async () => {
  let unavailable = 0;
  const check = new AccountRecheck(
    async () => {
      throw Error("offline");
    },
    () => assert.fail("must not accept"),
    () => {
      unavailable++;
    },
  );
  await check.check();
  await check.check();
  assert.equal(unavailable, 2);
});

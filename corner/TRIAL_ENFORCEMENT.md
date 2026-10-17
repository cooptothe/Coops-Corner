# Two-day trial preparation

CORNER_BETA_TRIALS defaults to 0. Deploying this code changes no current preview access and activates neither payments nor collection.

When explicitly enabled with private beta, new invited previews start an immutable 48-hour clock. Existing previews require an explicit operator start-trial action. Repeated starts return the original timestamp. New trials stop during the final 48 hours of beta. Paid access ends November 21, 2026 at 06:00 UTC, midnight Central. Operators remain exempt. Suspension never resets the clock.

Default signed-session checks for tools feeds enforce expiry. Accounts authentication, billing status, settings and personal tracker remain available after expiry. Restricted refresh routes return membership_required. Account shows actual membership expiry in Central time. Payment initiation stays disabled. This is not invoice creation or blockchain verification.

The beta_trials table is covered by the full SQLite account backup. Preserve it during restore. Activation requires a fresh account backup, a reviewed start list for current previews and restarting accounts and tools API. No activation command is included in this release. Server access restrictions apply on each request.

Expired members are redirected to Account without losing their login. Focus, visibility and periodic checks refresh server entitlement; simultaneous denial responses share one check. A pending check cannot restore a previous identity after logout. Known expiry removes feed content locally at the deadline.

Members who skip the $50 beta option can subscribe at launch for the standard $125/month. No automatic conversion or charge. Paying beta members lock in $50/month for the pregame standard-market package after launch. Founder status is derived from the existing server-managed founder flag, never from a client claim. Launch subscriptions and recurring payment collection are not activated.

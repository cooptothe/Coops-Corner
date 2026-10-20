# Cash-book replacement - October 20, 2026

The owner replaced PrizePicks with Caesars (`williamhill_us`) and Underdog with
Fanatics (`fanatics`). The official Odds API bookmaker list confirms these keys:
https://the-odds-api.com/sports-odds-data/bookmaker-apis.html

Scheduled prop standard group: existing six standard books plus Caesars and
Fanatics (eight total). Local prop requests: existing twelve main sources plus
these two cash books (fourteen total). Existing main-market request groups are
unchanged. Therefore the replacement does not cross another named-book billing
tier, change collection intervals or change the existing budget pools.

Both replacements can be prop reference sources with ordinary cash-price
de-vigging and default non-dominant reference weights. They are not assigned the
old DFS 50/50 median assumption, nor promoted to the highest sharpness tier.
Two other eligible references remain required and a target never references
itself. One-sided cash estimates retain their existing disclosed margin policy.

DFS sites are globally excluded from supported feed books, including stale
stored captures, environment reference overrides, coverage counts, Lab contracts
and the sportsbook picker. Local and deployed production paths disable DFS
pricing. Legacy API shape fields remain for compatibility but no DFS-derived
rows are emitted. Existing tracked wagers are not deleted or rewritten.

Publish with a stopped collector; reconcile fresh quota and renew the current
commit-specific root approval using collection_recover, then restart. The source
scope/job identity and cadence are preserved, so changing book lists cannot
replay missed ticks or reset previous usage/quarantines. The member web build
must also be refreshed to display the new labels and remove obsolete DFS help.

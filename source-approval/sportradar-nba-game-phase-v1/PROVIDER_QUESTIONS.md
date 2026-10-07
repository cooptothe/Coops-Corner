# Draft clarification request — not sent

Subject: NBA game-feed phase verification, failure semantics and access scope

We are evaluating your NBA game-level feed as evidence for a conservative pregame
eligibility check. We are not treating scheduled start time, cache duration or
fresh HTTP receipt as proof that a game has not started. Please identify the
applicable product/API version, endpoint and access tier for your answers.

1. What do `scheduled` and `created` guarantee about actual play? Can either remain
   visible after jump ball during collection failure, publication delay or failover?
   Does a repeated unchanged status mean the source positively reverified phase?
2. Which field or transport signal identifies the last positive verification of
   **game status**, rather than a roster/statistics update, cache refresh or HTTP
   response? Please provide timestamp units, timezone, clock assumptions and scope.
3. How can a client detect lost/partial coverage, data-collection outage, stale
   cache, replayed responses and failover? Can HTTP 200 and fresh Date coexist with
   stale phase? Which signals revoke confidence in a prior pregame status?
4. Is any maximum delay from actual jump ball to game-status publication bounded
   operationally or contractually? Separate collection, publication, caching and
   delivery. Please identify exceptions and whether these are guarantees or targets.
5. Is game REST status authoritative over schedule status? What should consumers
   do with conflicts or apparent status regressions? Does any push channel provide
   status-verification liveness, distinct from event/transport heartbeats?
6. For the v8 play-by-play candidate, what is cache behavior during `created`,
   delayed starts, interruption and outages? Do conditional GET/304 responses
   establish anything about source phase freshness? What call rates are permitted?
7. How should clients distinguish pre-start delay from an interruption after play?
   How should postponed/replacement games be mapped when IDs are not linked? Are
   there stable league references and documented correction/reuse semantics?
8. Which NBA season types and coverage levels satisfy your answers? Are preseason,
   international venues, extended-boxscore coverage or trial data exceptions?
9. Which package/tier permits access to the exact feed and retention of payloads,
   metadata and derived phase judgments for internal audit/replay? Please confirm
   applicable trial equivalence, exceptions, retention restrictions and allowed use.
10. Please identify the author/team, effective date, controlling documentation or
    agreement revision, and how changes/withdrawal of these assurances are notified.

An answer that no positive-verification timestamp or maximum latency guarantee
exists is useful. We will retain that limitation, not infer a guarantee from tests.

## Retaining a reply

Keep the original reply/export and attachment bytes in authorized private storage;
record content hashes, receipt time, sender/support-case provenance, exact scope,
and effective revision. Preserve adverse answers and follow-ups as new records.
Do not commit credentials, account tokens or private commercial terms to a public
repository. A redacted derivative needs its own digest and an explicit reference
to the access-controlled original. Provider clarification is evidence, not Corner
approval. No message has been sent and no subscription has been purchased.

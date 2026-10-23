# Parlay handoffs

FanDuel: existing indexed marketId/selectionId pairs. DraftKings: provider outcome tokens joined in the documented outcomes query; same-game combinations remain subject to book acceptance. BetMGM: provider fixture-market-option triplets joined with commas, with consistent state/origin; SGPs need book-specific grouping and remain manual. Missing IDs, duplicate tokens and mismatched destinations do not produce combined-slip links.

Every configured book can use its validated provider selection, market or event link via an accurately labelled Open button, plus individual leg links and Copy slip. A market/event link is never presented as a filled combined slip. Some exchanges have no parlay product; unsupported combined formats are not fabricated. These changes do not place wagers or buy additional data. Book acceptance and populated-slip behavior need real sportsbook verification; unit tests prove encoding and URL restrictions only.

Primary sources checked October 23, 2026:
- https://the-odds-api.com/releases/deep-links.html (links when available)
- https://sportsapi.pa.betmgm.com/restapi/elementsdeeplink.html (comma-separated option triplets)
- https://docs.oddsblaze.com/endpoints/parlay_rfq_engine/ (provider-produced DraftKings combined outcomes URL)

# Saved Lab lines and manual parlay recording

The Lab has a persistent research catalog (lab-catalog.sqlite3 next to the trends
cache). It reads saved collection snapshots without the actionable feed expiry
gate and can bootstrap from retained closing-line captures after withdrawal.
Existing local saved prop files are also supported. Exact line, source timestamp
and sportsbook are preserved; new observations replace older saved prices.

Collected props stay researchable through expiration, scope withdrawal, worker
pauses and service restarts. A recent-event slate covers the last 30 event days,
anchored to the last observed event if collection stops, so age alone cannot
empty it. No fake roster or props are generated when nothing was ever captured.
Past events are researchable and clearly dated. Archived prices are labelled
saved research lines; they are not used to create actionable EV opportunities.

The browser checks stored inventory every minute while visible and invalidates
cached reports when a quote changes. Current lines take precedence over saved
lines in the master list. Detail views retain the original as-of timestamp.
These reads do not request paid odds. The existing scheduled worker acquires new
prices at its approved cadence. The research catalog does not enable collection.

Parlay recording now uses the combined American odds, stake and placement time
entered by the user. The Review current odds button and freshness/availability/
price-acceptance gates were removed; there is no automatic review dependency.
Saved Lab selections and past event selections can be used for manual tracking.
Basic valid-field, same-book, unique-selection and 2–8-leg data constraints remain.
Only the parent wager affects bankroll; child prices remain reference metadata.
Combined return previews use the user's entered total odds, not multiplication
of historical leg prices. Neither recording nor opening a link places a wager.

The optional refreshParlay utility still checks current snapshots for callers
that explicitly need it; the parlay builder no longer calls that utility.
Feed freshness, EV calculations and quota limits are unchanged.

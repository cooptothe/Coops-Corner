# Devig method comparisons

Both EV feeds offer **Compare devig** on rows whose references contain complete,
matching markets. The method dropdown updates displayed probabilities, fair odds, EV, filters and
new bet-sizing inputs together. It never changes reference books or weights,
provider fetches, or previously tracked bet records. Selection is saved per account
and included in presets; App default restores the existing pricing policy. Main EV retains its proportional headline. Props retain power probability
and their existing lower-of-power-and-proportional EV policy. App default can show positive EV even when another method shows negative EV.
Each selected-method EV feed only shows positive edges under that selected method;
main-line candidates are repriced before qualification so newly positive bets are
not lost merely because App default would have excluded them. Invalid methods
exclude the affected paired market; one-sided margin models stay separate.

Each book is devigged separately, then pooled using the same existing reference
weights and source-identity normalization. Targets remain excluded from references.
Multiplicative divides raw implied probabilities by their sum; additive subtracts
an equal share of overround; power solves a common exponent; classical Shin solves
a nonnegative informed-fraction model. Shin equals additive on a two-outcome
overround market. Negative additive probabilities are rejected, not clamped. Shin
is unavailable for underrounds. A method is omitted if invalid for any reference.

Worst Case selects the lowest EV across valid pooled methods for that bet. For
back bets this uses the lowest selection probability; for lays it uses the highest.
It is not a confidence bound, and per-selection worst-case probabilities need not
sum to one. Fees use the same target commission assumptions. Push-capable markets
remain conditional on decisive settlement; no push, void or dead-heat mass is inferred.

One-sided reference populations keep their existing observed/assumed margin models.
They do not receive fabricated Additive/Power/Shin comparisons. A one-sided target
can receive comparisons if its references have genuine complete matching pairs.

Numerical calculations use Decimal with bounded precision and cached immutable
price/weight vectors. Comparison values are delivered to 12 decimal places;
selected main-feed qualification excludes numerical dust at or below 1e-20. Cached distributions never replace upstream freshness,
withdrawal or eligibility checks. Each cache is bounded at 4096 entries. Charts
and comparison tables are created only on opening the dialog; feed virtualization
is preserved. No provider calls, acquisition changes or additional credits.

The formulas are standard margin models, not a reproduction of OddsJam proprietary
algorithms. None is empirically validated for our deployment merely by being added.

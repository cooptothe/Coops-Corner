# Automatic one-sided prop pricing

Paired reference prices remain the default when available, including exact
Yes/No pairs for scorer markets. See `SCORER_RESEARCH.md` for independent
one-sided sensitivity research and its limits. Otherwise the app
estimates each reference book's margin using complete binary prices from at least
three other players in the same event and exact prop market. Alternate lines do
not add independent samples: each player's maximum observed overround counts once.
The median of those samples supplies the central estimate; their maximum supplies
a sensitivity estimate. EV uses the lower probability after fees. Neither the
maximum nor the resulting EV is a statistical confidence bound. Transferring
proportional margin between players remains a modeling assumption.

Each reference's complete exact pair is used directly where available. Otherwise
`overround = 1 / over_price + 1 / under_price - 1` is estimated from the other
players. Samples outside 0 through 50 percent and duplicate quote groups are
excluded. At least two other reference books must qualify. No margin transfers
between events, prop markets or books. The target player's other lines never
supply its own margin estimate. Model rows expose per-book sample counts, medians
and maxima as `margin_evidence`. Pure yes-only markets have no complete pairs from
which to learn a margin, so automatic transfer cannot price them. The member
feed now explicitly falls back to the provisional policy described below.

## Member-feed fallback policy

In automatic mode, when a reference has no usable pair or observed margin sample,
the retained-props feed uses a **10% proportional overround assumption** for that
reference's central estimate and **20%** for its stress estimate. Other reference
books still use their better paired/observed evidence. At least two non-target
references must qualify. EV uses the lower pooled probability after supported
target fees. Rows disclose both policy percentages and identify fallback books.
These are policy choices, not empirically estimated holds or confidence limits.

The props feed shows only strictly positive EV that also meets the user's minimum
EV and all other filters. Zero, negative and unavailable EV do not appear as
opportunities. The 20% scenario remains a proportional-margin scenario, not a
guaranteed worst case; the separate allocation sensitivity retains that distinction.
The optional explicit user override replaces this automatic policy on that request.
No API key, provider request, collector activation or billing change is involved.

Open **One-sided props pricing** for details and an optional explicit margin
override from 0 through 50 percent. Blank uses the evidence-first policy above. The setting
saves with account preferences and presets. Set maximum market width to **No
limit** to include quotes whose opposite side is unavailable.

If two complete reference pairs are available, the existing paired model wins.
Otherwise the model requires two other eligible books quoting the exact
event, player, market, line and side. It excludes the target book and DFS prices.
With normalized reference weights `w`, decimal prices `d`, and explicit margin
assumption `m`, the modeled probability is:

`p = sum(w / d) / (1 + m)`

This assumes proportional margin allocation. One-sided odds alone cannot identify
the true margin or fair probability. The assumption is neither fitted to results
nor empirically calibrated. A zero input explicitly assumes zero margin; it is
never a default. Rows identify the assumption used. Target fees are applied before
calculating EV; unresolved target fees remain ineligible. Integer lines retain
conditional-on-no-push treatment. Pick'em lineup payouts need a separate model.

Example: two references at decimal 2.00, with a 10% margin assumption, imply
`p = 0.5 / 1.1`. A target at 3.00 produces modeled EV of 36.36% before any target
commission. This demonstrates arithmetic, not predictive accuracy.

`GET /api/refresh/v1/props?one_sided_margin=0.10` reprices retained quotes. It
requires the existing account access checks, accepts ratios from 0 to 0.50,
and performs no provider request. Invalid inputs return 422. Omitting the
parameter uses observed margin transfer where supported, otherwise leaves EV unavailable. Assumptions are request-scoped.

Parlay tracking now asks for accepted American odds (`+325`, `-150`). Conversion
happens before the existing decimal-odds tracking API is called; stored bet and
payout calculations retain their decimal representation. Polymarket `.us` links
are unchanged.

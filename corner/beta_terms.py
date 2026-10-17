"""Confirmed beta offer; pure timing policy, not an activated access guard."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, localcontext

VERSION = 'beta-2026-11-20-two-day-v1'
TRIAL_SECONDS = 2 * 24 * 60 * 60
PRICE_USD_CENTS = 5000
ASSETS = {'XRP': ('xrpl-mainnet', 6), 'HBAR': ('hedera-mainnet', 8),
          'XLM': ('stellar-mainnet', 7)}
# End of November 20 in America/Chicago (CST after the November DST transition).
BETA_END = datetime(2026, 11, 21, 6, tzinfo=timezone.utc).timestamp()
LAST_TRIAL_START = BETA_END - TRIAL_SECONDS


def entitlement(kind, started_at, now):
    """Two full days from enrollment; all member access ends at beta close.

    Stop new trials in the final 48 hours rather than advertising a truncated
    two-day trial. The caller must persist a single immutable enrollment time.
    """
    if kind == 'operator':
        return {'state':'operator', 'expires_at':None}
    if kind not in ('preview', 'paid_beta'):
        return {'state':'unavailable', 'expires_at':None}
    if now < started_at:
        return {'state':'unavailable', 'expires_at':None}
    expires = BETA_END if kind == 'paid_beta' else min(started_at+TRIAL_SECONDS, BETA_END)
    state = ('paid' if kind == 'paid_beta' else 'trial') if now < expires else 'expired'
    return {'state':state, 'expires_at':expires}


def trial_available(now):
    return now <= LAST_TRIAL_START


def quote_amount(asset, usd_per_coin):
    """Exact $50 amount in native base units, rounded up by at most one unit.

    Caller must supply a verified timestamped USD quote and an expiry; this pure
    calculator never fetches a rate or treats it as valid market evidence.
    """
    if asset not in ASSETS or not isinstance(usd_per_coin, str) or len(usd_per_coin)>50:
        raise ValueError('Choose XRP, HBAR or XLM and a decimal-string USD quote.')
    try:
        rate = Decimal(usd_per_coin)
    except InvalidOperation:
        raise ValueError('A positive, finite USD quote is required.') from None
    if not rate.is_finite() or not Decimal('0.00000001') <= rate <= Decimal('100000000'):
        raise ValueError('USD quote is outside supported bounds.')
    decimals = ASSETS[asset][1]
    with localcontext() as context:
        context.prec = 80
        units = int((Decimal(50) / rate * 10**decimals).to_integral_value(rounding=ROUND_CEILING))
        amount = format(Decimal(units).scaleb(-decimals), f'.{decimals}f')
    return {'asset':asset, 'network':ASSETS[asset][0], 'amount_base_units':str(units),
            'amount':amount, 'usd_cents':PRICE_USD_CENTS, 'usd_per_coin':str(rate)}

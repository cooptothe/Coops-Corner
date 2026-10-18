"""Calendar-day restriction for LOCAL manual alternate markets only."""
from datetime import datetime, timezone
import pytz

CENTRAL = pytz.timezone('America/Chicago')


def markets_for_event(markets, starts_at, now=None):
    now = now or datetime.now(timezone.utc)
    start = datetime.fromisoformat(starts_at.replace('Z', '+00:00'))
    if start.utcoffset() is None or now.utcoffset() is None:
        raise ValueError('Timezone-aware event start and current time required')
    today = start > now and start.astimezone(CENTRAL).date() == now.astimezone(CENTRAL).date()
    return tuple(key for key in markets if today or not (key.startswith('alternate_') or key.endswith('_alternate')))

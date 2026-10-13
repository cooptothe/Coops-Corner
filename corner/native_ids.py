"""Retain bookmaker-native selection IDs; no links are synthesized here."""
import re
from urllib.parse import urlsplit, parse_qs

def _id(value):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9._:-]{1,180}', value) else None

def native_ids(book, *, event=None, market=None, outcome=None, link=None):
    ids = {key: _id(value) for key, value in (('event', event), ('market', market), ('outcome', outcome))}
    if isinstance(link, str):
        try:
            query = parse_qs(urlsplit(link).query)
            if book == 'fanduel':
                ids['market'] = ids['market'] or _id((query.get('marketId') or [None])[0])
                ids['outcome'] = ids['outcome'] or _id((query.get('selectionId') or [None])[0])
        except ValueError:
            pass
    return {k: v for k, v in ids.items() if v} or None

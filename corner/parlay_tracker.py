"""Parlay children carry selections and results; only their parent carries money."""
from datetime import datetime
import re

MAX_PARLAY_LEGS = 8
LEG_RESULTS = ('pending', 'won', 'lost', 'push', 'void')

def prepare_legs(items, parent_book, *, fail, text, parse_odds, parse_when, clean_ref):
    if not isinstance(items, list) or not 2 <= len(items) <= MAX_PARLAY_LEGS:
        fail('A parlay needs 2–8 legs')
    saved, keys, matchups = [], set(), []
    for item in items:
        if not isinstance(item, dict):
            fail('Each parlay leg must be an object')
        key = text(item.get('key'), 'leg key', required=True, limit=300)
        event = text(item.get('event_id'), 'leg event', required=True, limit=180)
        matchup = text(item.get('matchup'), 'leg matchup', required=True, limit=200)
        start = parse_when(item.get('starts_at'), 'leg start time')
        if not start:
            fail('Every parlay leg needs a start time')
        fixture = (re.sub(r'\s+(?:@|at|vs\.?)\s+', ' at ', ' '.join(matchup.lower().split())), start)
        if key in keys:
            fail('Duplicate parlay leg')
        ref=clean_ref(item.get('ref'))
        market=text(item.get('market'), 'leg market', required=True, limit=120)
        for previous, previous_fixture in zip(saved,matchups):
            if (previous['event_id']==event or previous_fixture==fixture) and previous['market']==market and all(previous['ref'].get(k)==ref.get(k) for k in ('market_key','player','prop_market')):
                fail('Choose only one selection per player/market in the same game')
        if item.get('book') != parent_book:
            fail('All parlay legs must use the same sportsbook')
        if item.get('source') not in ('ev', 'prop'):
            fail('Unknown parlay leg source')
        keys.add(key); matchups.append(fixture)
        saved.append(dict(key=key, event_id=event, book=parent_book, matchup=matchup, starts_at=start,
                          source=item['source'], sport_key=text(item.get('sport_key'), 'leg sport', limit=60),
                          market=market,
                          selection=text(item.get('selection'), 'leg selection', required=True, limit=200),
                          odds=parse_odds(item.get('odds')), ref=ref,
                          status='pending'))
    return saved

def suggested_result(legs):
    if any(leg['status'] == 'lost' for leg in legs):
        return 'lost'
    if any(leg['status'] == 'pending' for leg in legs):
        return None
    if all(leg['status'] in ('void', 'push') for leg in legs):
        return 'void'
    return 'won'

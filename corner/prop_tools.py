"""Fresh cash prop quotes for exact-contract cover, middle and promo tools.

No EV gate, provider requests or DFS payout interpretation. The same player's
standard/alternate contracts share a statistic coordinate, never another player.
"""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256

from corner.prop_markets import market_meta
from corner.pricing import DFS, fee_policy
from corner.book_policy import supported_book


def best_middles(bets, refund_possible):
    """Best executable cross-book price pair for each distinct line window.

    Every line participates. Dominated book permutations are not separate feed
    rows (as with the best-price main arbitrage cover); all quotes remain in
    the catalog for promo calculations. Payoffs still use the core calculator.
    """
    from corner.featured_middles import calculate_middle
    lines = {}
    def net(bet):
        return 1 + (bet.decimal_odds - 1) * (1 - bet.commission_rate)
    for bet in bets:
        lines.setdefault((bet.side, bet.line), []).append(bet)
    # With a distinct-book constraint, at most two best books per side suffice.
    ranked = {}
    for key, offers in lines.items():
        ordered = sorted(offers, key=lambda b: (-net(b), b.sportsbook_id, b.quote_id))
        seen=set(); chosen=[]
        for bet in ordered:
            if bet.sportsbook_id not in seen:
                chosen.append(bet);seen.add(bet.sportsbook_id)
            if len(chosen)==2:break
        ranked[key]=chosen
    results=[]
    for (side,lower), firsts in sorted(ranked.items()):
        if side!='over':continue
        for (other,upper), seconds in sorted(ranked.items()):
            if other!='under':continue
            # Exact integer statistic domain: at least one integer strictly
            # between the two lines is necessary for both full wins.
            if int(lower.to_integral_value(rounding='ROUND_FLOOR'))+1 > int(upper.to_integral_value(rounding='ROUND_CEILING'))-1:
                continue
            pairs=[(a,b) for a in firsts for b in seconds if a.sportsbook_id!=b.sportsbook_id]
            if not pairs:continue
            a,b=min(pairs,key=lambda pair:(-min(net(pair[0]),net(pair[1])), -(net(pair[0])+net(pair[1])),pair[0].quote_id,pair[1].quote_id))
            results.append(calculate_middle(contract_id=a.contract_id,first=a,second=b,refund_possible=refund_possible))
    return tuple(results)


def merge_props(raw, *, now, data=None):
    from pipelines import props_ingestion as props
    data = props.prune(deepcopy(props.load() if data is None else data), now, props.MAX_AGE)
    result = deepcopy(raw)
    books = {b['id']: b for b in result['books']}
    games = {g['id']: g for g in result['games']}
    newest = [result['captured_at'], result['observed_at']]
    for event_id, event in data['events'].items():
        # Provider event identity is independent of the PostgreSQL UUID for main lines.
        game_id = 'prop:' + event_id
        groups = {}
        for key, stored in event['markets'].items():
            meta = market_meta(event['sport_key'], key)
            if meta is None:
                continue
            for q in stored['quotes']:
                if q['book'] in DFS or not supported_book(q['book']):
                    continue
                policy = fee_policy(q['book'])
                if policy.commission is None:
                    continue
                try:
                    price = Decimal(q['price'])
                    point = None if q['point'] is None else Decimal(q['point'])
                    if not price.is_finite() or not 1 < price <= Decimal('1e12'):
                        continue
                    if q['side'] not in (0, 1) or not q['player'].strip():
                        continue
                    if meta.sides == ('Over', 'Under') and (point is None or not point.is_finite() or point < 0 or point * 2 != (point * 2).to_integral_value()):
                        continue
                    at = q.get('updated_at') or stored['captured_at']
                    stamp = datetime.fromisoformat(at.replace('Z', '+00:00'))
                    if not 0 <= (now - stamp).total_seconds() < props.MAX_AGE:
                        continue
                except (ValueError, TypeError, ArithmeticError):
                    continue
                base = key.removesuffix('_alternate')
                identity = (base, q['player'], None if point is None else format(point.normalize(), 'f'))
                group = groups.setdefault(identity, {'meta': meta, 'keys': set(), 'cells': {}})
                group['keys'].add(key)
                cell = (q['book'], q['side'])
                previous = group['cells'].get(cell)
                # Same contract may appear in standard and alternate response lists.
                # Newest quote wins; equal-time conflicting prices are excluded.
                candidate = {**q, 'price': str(price), 'at': at}
                if previous is None or at > previous['at']:
                    group['cells'][cell] = candidate
                elif at == previous['at'] and candidate['price'] != previous['price']:
                    group['cells'][cell] = {**candidate, 'conflict': True}
        for (base, player, point), group in groups.items():
            cells = {k: q for k, q in group['cells'].items() if not q.get('conflict')}
            if not cells:
                continue
            key = base + '_alternate' if base + '_alternate' in group['keys'] else base
            meta = group['meta']
            sides = ('over', 'under') if meta.sides == ('Over', 'Under') else ('yes', 'no')
            contract_id = 'prop:' + sha256(f'{event_id}|{base}|{player}|{point}'.encode()).hexdigest()
            present_books = sorted({b for b, _ in cells})
            prices = {b: [cells[(b,s)]['price'] if (b,s) in cells else None for s in (0,1)] for b in present_books}
            observed = {b: min(q['at'] for (book, _),q in cells.items() if book == b) for b in present_books}
            result['contracts'].append(dict(id=contract_id, game_id=game_id, market_key=key,
                subject=player, refund_possible=point is not None and Decimal(point) == Decimal(point).to_integral_value(),
                selections=[dict(id=side, name=f'{player} {meta.sides[i]}', side=side, point=point) for i,side in enumerate(sides)],
                prices=prices, lay_prices={}, observed=observed,
                links={b:[cells.get((b,s),{}).get('links') for s in (0,1)] for b in present_books},
                source_ids={b:[cells.get((b,s),{}).get('source_ids') for s in (0,1)] for b in present_books}))
            games[game_id] = dict(id=game_id, sport_key=event['sport_key'], competition=event['sport_key'],
                name=f"{event['away_team']} at {event['home_team']}", starts_at=event['commence_time'],
                scope='full_game', participants=sorted([event['home_team'],event['away_team']]))
            for b in present_books:
                policy=fee_policy(b)
                books[b]=dict(id=b,name=b,commission=str(policy.commission),fee_status=policy.status)
            newest.extend(observed.values())
    result['books']=list(books.values())
    result['games']=list(games.values())
    latest=max(newest,key=lambda x:datetime.fromisoformat(x.replace('Z','+00:00')))
    result['captured_at']=result['observed_at']=latest
    return result

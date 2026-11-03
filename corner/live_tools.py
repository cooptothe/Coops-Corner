"""Live snapshot candidates using the existing devig, cover and middle math.

Never an execution guarantee. Source-time proximity is necessary but cannot
prove identical game state or settlement rules across sportsbooks.
"""
from __future__ import annotations
from decimal import Decimal as D
from itertools import combinations
from functools import lru_cache
import json
from datetime import datetime, timezone
from api.catalog import wire, digest
from typing import Any
from corner.featured_tools import MatchedMarket, Offer, calculate_back_cover, ToolInputError
from corner.featured_ev import calculate_featured_ev
from corner.featured_middles import LineBet, calculate_middle, _full_win_window
from corner.links import clean_links
from corner.pricing import fee_policy
from corner.reference_policy import sufficient_references
from corner.collection_policy import parse

MAX_SKEW = 10

def opportunities(event: dict[str, Any], devig_method: str = 'current') -> list[dict[str, Any]]:
    # Unchanged source snapshots reuse the same analysis across cached API reads.
    return _analyze(json.dumps(event,sort_keys=True,separators=(',',':')), devig_method)

@lru_cache(maxsize=512)
def _analyze(encoded: str, devig_method: str) -> list[dict[str, Any]]:
    event: dict[str, Any] = json.loads(encoded)
    groups: dict[tuple[str,str],list[tuple[str,dict[str,Any]]]] = {}
    for book in event['bookmakers']:
        for market in book['markets']:
            key = market['key']
            if key == 'h2h': line = ''
            else:
                outcome = next(o for o in market['outcomes'] if o['name'] == ('Over' if key=='totals' else event['home_team']))
                line = str(D(str(outcome['point'])).normalize())
                # Quarter-line split settlements require more than two winner states.
                if D(line)*2 != (D(line)*2).to_integral_value(): continue
            groups.setdefault((key,line),[]).append((book['key'],market))
    book_links = {b['key']:b.get('link') for b in event['bookmakers']}
    result: list[dict[str,Any]] = []
    quotes: dict[str,dict[str,Any]] = {}
    def attach(candidate, calculation, offers, capital, minimum=None, ev_ratio=None):
        ids = [o.quote_id for o in offers]
        candidate['tool_row'] = {
            'id': 'live:'+digest([candidate['kind'],ids]), 'game_id':event['id'],
            'contract_id':calculation.contract_id, 'market_key':candidate['market'],
            'kind':'positive_ev' if candidate['kind']=='ev' else candidate['kind'],
            'quote_ids':ids,'sportsbook_ids':sorted({o.sportsbook_id for o in offers}),'capital_required':format(capital, 'f'),
            'minimum_profit':None if minimum is None else format(minimum, 'f'),
            'conditional_ev_ratio':None if ev_ratio is None else format(ev_ratio, 'f'),
            'oldest_observed_at':datetime.fromtimestamp(candidate['expires_at']-90,timezone.utc).isoformat(),
            'calculation':wire(calculation)}
        needed=set(ids)
        for ref in getattr(calculation,'reference_books',()): needed.update(ref.quote_ids)
        candidate['quotes']=[quotes[q] for q in sorted(needed)]
        result.append(candidate)
    line_bets: list[tuple[LineBet,float]] = []
    for (key,line), blocks in groups.items():
        # Drop duplicate bookmaker blocks rather than double-weight them.
        counts = {b:sum(1 for other,_ in blocks if other==b) for b,_ in blocks}
        blocks = [(b,m) for b,m in blocks if counts[b]==1]
        if not blocks: continue
        newest = max(parse(m['last_update']).timestamp() for _,m in blocks)
        blocks = [(b,m) for b,m in blocks if newest-parse(m['last_update']).timestamp()<=MAX_SKEW]
        selections = tuple(sorted(o['name'] for o in blocks[0][1]['outcomes']))
        contract = f"live:{event['sport_key']}:{event['id']}:{key}:{line}"
        refund = key != 'h2h' and D(line) == D(line).to_integral_value()
        matched = MatchedMarket(contract,key,selections,refund)
        refs, executable, source_times = [], [], {}
        for book,market in blocks:
            if tuple(sorted(o['name'] for o in market['outcomes'])) != selections: continue
            rate = fee_policy(book).commission
            source_times[book] = parse(market['last_update']).timestamp()
            for outcome in market['outcomes']:
                quote = f"{contract}:{book}:{outcome['name']}"
                offer = Offer(quote,contract,key,outcome['name'],book,D(str(outcome['price'])),D(0))
                refs.append(offer)
                side = ('over' if outcome['name']=='Over' else 'under') if key=='totals' else ('home' if outcome['name']==event['home_team'] else 'away' if outcome['name']==event['away_team'] else 'draw')
                quotes[quote]={'id':quote,'game_id':event['id'],'contract_id':contract,
                    'market_key':key,'sportsbook_id':book,'selection_id':outcome['name'],
                    'selection_name':outcome['name'],'side':side,
                    'point':str(outcome['point']) if 'point' in outcome else None,
                    'decimal_odds':str(outcome['price']),
                    'commission_rate':str(rate) if rate is not None else None,
                    'fee_status':'known' if rate is not None else 'unknown',
                    'evidence_kind':'retained_provider_quote','current_availability':'unverified',
                    'observed_at':market['last_update'],'provider_updated_at':market['last_update'],'links':clean_links(book, book_links.get(book), market.get('link'), outcome.get('link'))}
                if rate is not None:
                    offer = Offer(quote,contract,key,outcome['name'],book,D(str(outcome['price'])),rate)
                    executable.append(offer)
                    if key != 'h2h':
                        side = ('over' if outcome['name']=='Over' else 'under') if key=='totals' else ('home' if outcome['name']==event['home_team'] else 'away')
                        line_bets.append((LineBet(quote,book,f"live:{event['sport_key']}:{event['id']}:{key}",key,side,D(str(outcome['point'])),offer.decimal_odds,D(50),rate),source_times[book]))
        for target in executable:
            books = tuple(sorted({r.sportsbook_id for r in refs if r.sportsbook_id!=target.sportsbook_id}))
            if not sufficient_references(books,event['sport_key']): continue
            try:
                ev = calculate_featured_ev(matched,target,[r for r in refs if r.sportsbook_id in books],required_reference_books=books,sport_key=event['sport_key'],devig_method=devig_method)
            except ToolInputError: continue
            if ev.conditional_ev_ratio_on_capital > 0:
                attach({'kind':'ev','market':key,'line':line,'selection':target.selection_id,
                    'book':target.sportsbook_id,'decimal_odds':format(target.decimal_odds, 'f'),
                    'fair_probability':format(ev.conditional_fair_probability, 'f'),
                    'ev_percent':format(ev.conditional_ev_ratio_on_capital*100, 'f'),'reference_books':list(books),'expires_at':min(source_times.values())+90}, ev, [target], ev.capital_at_risk, ev_ratio=ev.conditional_ev_ratio_on_capital)
        if executable and set(o.selection_id for o in executable)==set(selections):
            cover = calculate_back_cover(matched,executable,total_stake=D(100))
            if len({leg.sportsbook_id for leg in cover.legs}) == 1:
                # Equal-price ties can select both sides at one book. Search
                # the cross-book alternatives rather than hide a valid cover.
                lone = cover.legs[0].sportsbook_id
                alternatives = []
                for side in selections:
                    subset = [o for o in executable if not (o.sportsbook_id==lone and o.selection_id==side)]
                    if set(o.selection_id for o in subset) == set(selections):
                        candidate = calculate_back_cover(matched,subset,total_stake=D(100))
                        if len({leg.sportsbook_id for leg in candidate.legs})>1: alternatives.append(candidate)
                if alternatives: cover=max(alternatives,key=lambda c:c.minimum_decisive_profit)
            if cover.minimum_decisive_profit>0 and len({leg.sportsbook_id for leg in cover.legs})>1:
                attach({'kind':'arbitrage','market':key,'line':line,
                    'profit_per_100':format(cover.minimum_decisive_profit, 'f'),'refund_possible':refund,'expires_at':min(source_times.values())+90,
                    'legs':[{'book':leg.sportsbook_id,'selection':leg.selection_id,'decimal_odds':str(leg.decimal_odds),'stake':str(leg.stake)} for leg in cover.legs]}, cover, cover.legs, cover.total_stake, cover.minimum_modeled_profit)
    for (first,at),(second,bt) in combinations(line_bets,2):
        if (first.contract_id!=second.contract_id or first.side==second.side or first.sportsbook_id==second.sportsbook_id or abs(at-bt)>MAX_SKEW): continue
        if not _full_win_window(first.market_key,first.side,first.line,second.side,second.line): continue
        try:
            middle = calculate_middle(contract_id=first.contract_id,first=first,second=second,refund_possible=False)
        except ToolInputError: continue
        if middle.double_win_ranges:
            attach({'kind':'middle','market':first.market_key,
                'window':list(middle.double_win_ranges),'expires_at':min(at,bt)+90,
                'worst_profit_per_100':format(middle.payoff.minimum_modeled_profit, 'f'),
                'best_profit_per_100':format(middle.payoff.maximum_modeled_profit, 'f'),
                'legs':[{'book':b.sportsbook_id,'selection':b.side,'line':str(b.line),'decimal_odds':str(b.decimal_odds),'stake':str(b.stake)} for b in (first,second)]}, middle, (first,second), first.stake+second.stake, middle.payoff.minimum_modeled_profit)
    for candidate in result:
        candidate.update(availability_verified=False,game_state_verified=False,
                         settlement_rules_verified=False,basis='snapshot_estimate')
    return result

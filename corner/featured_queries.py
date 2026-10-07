"""Read-only canonical quote selection for the featured pure calculators.

Caller supplies the complete approved/mocked settlement population and commission
configuration. This bridge verifies registry shape, not external rules authority.
Use a caller-owned REPEATABLE READ, READ ONLY transaction for a coherent view.
"""
from dataclasses import dataclass
from decimal import Decimal
from datetime import timedelta
from fractions import Fraction
import hashlib
import json

from psycopg2.extras import RealDictCursor

from corner.featured_matching import identity, require
from corner.featured_store import QuoteStream, read_featured_streams
from corner.featured_tools import MatchedMarket, Offer, calculate_back_cover, calculate_back_lay

BACK_TYPES = {'moneyline':'h2h','spread':'spreads','total':'totals','outright':'outrights'}


@dataclass(frozen=True)
class CalculationInputs:
    market: MatchedMarket
    offers: tuple[Offer, ...]
    streams: tuple[QuoteStream, ...]

    def back_cover(self, *, total_stake, stake_increment=Decimal('0.01')):
        return calculate_back_cover(self.market, [o for o in self.offers if o.market_key==self.market.market_key],
                                    total_stake=total_stake,stake_increment=stake_increment)

    def back_lay(self, *, back_quote_id, lay_quote_id, back_stake, stake_increment=Decimal('0.01')):
        offers = {o.quote_id:o for o in self.offers}
        require(back_quote_id in offers and lay_quote_id in offers, "quote not eligible in this snapshot")
        return calculate_back_lay(self.market, offers[back_quote_id],offers[lay_quote_id],
                                  back_stake=back_stake,stake_increment=stake_increment)

    def expected_value(self, *, target_quote_id, required_reference_books, stake=Decimal('1')):
        from corner.featured_ev import calculate_featured_ev
        offers = {o.quote_id:o for o in self.offers}
        require(target_quote_id in offers, "quote not eligible in this snapshot")
        books = tuple(required_reference_books)
        references = [o for o in self.offers if o.sportsbook_id in books and o.market_key==self.market.market_key]
        return calculate_featured_ev(self.market, offers[target_quote_id], references,
                                     required_reference_books=books, stake=stake)

    def promo_conversion(self, *, back_quote_id, lay_quote_id, terms, stake_increment=Decimal('0.01'),
                        maximum_lay_stake=None, maximum_lay_liability=None):
        from corner.featured_promos import convert_promo
        offers = {o.quote_id:o for o in self.offers}
        require(back_quote_id in offers and lay_quote_id in offers, "quote not eligible in this snapshot")
        return convert_promo(self.market, offers[back_quote_id], offers[lay_quote_id], terms,
                             stake_increment=stake_increment, maximum_lay_stake=maximum_lay_stake,
                             maximum_lay_liability=maximum_lay_liability)

    def promo_back_conversion(self, *, promo_quote_id, hedge_quote_id, terms,
                              stake_increment=Decimal('0.01'), maximum_hedge_stake=None):
        from corner.featured_promos import convert_promo_back_hedge
        offers = {o.quote_id:o for o in self.offers}
        require(promo_quote_id in offers and hedge_quote_id in offers, "quote not eligible in this snapshot")
        return convert_promo_back_hedge(self.market, offers[promo_quote_id], offers[hedge_quote_id], terms,
                                        stake_increment=stake_increment, maximum_hedge_stake=maximum_hedge_stake)


def _market(cur, market_id):
    cur.execute('''SELECT m.event_id,m.subject_participant_id,t.code AS market_type,s.code AS scope
        FROM corner.markets m JOIN corner.market_types t ON t.id=m.market_type_id
        JOIN corner.scopes s ON s.id=m.scope_id WHERE m.id=%s''',(market_id,))
    market = cur.fetchone()
    require(market is not None and market['subject_participant_id'] is None, "unknown or subject-specific market")
    cur.execute('''SELECT o.id,o.selected_participant_id,o.point,s.code AS side FROM corner.outcomes o
        JOIN corner.outcome_sides s ON s.id=o.outcome_side_id WHERE o.market_id=%s''',(market_id,))
    return market, {str(row['id']):row for row in cur.fetchall()}


def _shape(family, all_outcomes, selected, refund_possible):
    require(set(selected) <= set(all_outcomes), "outcome belongs to another market")
    rows = [all_outcomes[x] for x in selected]
    if family in {'h2h','outrights'}:
        require(set(selected) == set(all_outcomes), "explicit population omits registered outcomes")
        require(all(r['point'] is None for r in rows), "winner markets must not contain lines")
        if family == 'h2h':
            sides = {r['side'] for r in rows}
            require(sides in ({'home','away'},{'home','away','draw'}) and len(sides)==len(rows), "invalid moneyline population")
        else:
            require(all(r['side']=='entrant' for r in rows), "outright entrant outcomes required")
        participants = [str(r['selected_participant_id']) for r in rows if r['side']!='draw']
        require(len(set(participants))==len(participants) and 'None' not in participants, "distinct participants required")
        require(all(r['selected_participant_id'] is None for r in rows if r['side']=='draw'), "draw cannot select participant")
    else:
        require(len(rows)==2 and all(r['point'] is not None for r in rows), "two explicit line outcomes required")
        require(all((Fraction(r['point'])*2).denominator==1 for r in rows), "quarter/split lines require richer payoff model")
        if family=='spreads':
            require({r['side'] for r in rows}=={'home','away'} and sum(Fraction(r['point']) for r in rows)==0,
                    "spread lines must be exact opposites")
            require(all(r['selected_participant_id'] is not None for r in rows)
                    and rows[0]['selected_participant_id']!=rows[1]['selected_participant_id'], "distinct spread participants required")
        else:
            require({r['side'] for r in rows}=={'over','under'} and rows[0]['point']==rows[1]['point']
                    and all(r['selected_participant_id'] is None for r in rows), "totals must share an exact threshold")
        if any(Fraction(r['point']).denominator==1 for r in rows):
            require(refund_possible, "integer lines require explicit push/refund modeling")


def read_calculation_inputs(conn, *, market_id, outcome_ids, sportsbook_ids, assessed_at, max_age,
                            max_input_skew, settlement_identity, refund_possible, commissions,
                            lay_market_id=None):
    """Supply exact canonical IDs; no automatic market or settlement substitution.

    Missing/stale/suspended/unavailable streams are returned but excluded from offers.
    Back covers still require every expected selection when calculation is invoked.
    Completeness of the registry and actual rule applicability remain caller inputs.
    """
    require(not conn.autocommit and conn.isolation_level==2, "REPEATABLE READ transaction required")
    with conn.cursor() as cur:
        cur.execute('SHOW transaction_read_only')
        require(cur.fetchone()[0]=='on', "READ ONLY transaction required")
    identity(market_id)
    outcomes, books = tuple(outcome_ids), tuple(sportsbook_ids)
    require(len(outcomes)>=2 and bool(books), "explicit outcomes and sportsbooks required")
    require(len(set(outcomes))==len(outcomes) and len(set(books))==len(books), "duplicate selection/book")
    for value in outcomes+books:
        identity(value)
    require(type(refund_possible) is bool, "explicit refund branch required")
    require(isinstance(settlement_identity,str) and bool(settlement_identity.strip()), "explicit settlement identity required")
    require(isinstance(max_input_skew,timedelta) and max_input_skew>=timedelta(0), "nonnegative skew required")
    require(set(commissions)==set(books), "explicit commission required for every requested book")
    for rate in commissions.values():
        require(isinstance(rate,Decimal) and rate.is_finite() and 0<=rate<1, "invalid commission")
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        metadata, registered = _market(cur,market_id)
        family = BACK_TYPES.get(metadata['market_type'])
        require(family is not None, "back market must anchor calculation")
        require(metadata['scope']==('competition' if family=='outrights' else 'full_game'), "unsupported market scope")
        _shape(family,registered,outcomes,refund_possible)
        lay_mapping = {}
        if lay_market_id is not None:
            identity(lay_market_id)
            require(family in {'h2h','outrights'}, "no featured lay for spread/total")
            lay_metadata, lay_registered = _market(cur,lay_market_id)
            require(lay_metadata['market_type']==metadata['market_type']+'_lay'
                    and lay_metadata['event_id']==metadata['event_id'] and lay_metadata['scope']==metadata['scope'],
                    "lay market must match event, scope and family")
            signature = lambda row:(str(row['selected_participant_id']),row['side'],row['point'])
            back_signatures = {signature(registered[o]):o for o in outcomes}
            require(len(back_signatures)==len(outcomes), "ambiguous outcome structure")
            for outcome_id,row in lay_registered.items():
                require(signature(row) in back_signatures, "lay selection outside back population")
                lay_mapping[outcome_id] = back_signatures[signature(row)]
            require(len(lay_mapping)==len(outcomes) and set(lay_mapping.values())==set(outcomes), "lay population mismatch")
    configuration = {'market_id':market_id,'outcomes':sorted(outcomes),'settlement_identity':settlement_identity,
                     'refund_possible':refund_possible}
    contract_id = 'featured:' + hashlib.sha256(json.dumps(configuration,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    contract = MatchedMarket(contract_id,family,tuple(sorted(outcomes)),refund_possible)
    pairs = tuple((o,b) for o in sorted(outcomes+tuple(lay_mapping)) for b in sorted(books))
    streams = read_featured_streams(conn,streams=pairs,assessed_at=assessed_at,max_age=max_age)
    eligible = [s for s in streams if s.reason is None]
    if eligible:
        times = [s.observed_at for s in eligible]
        require(max(times)-min(times)<=max_input_skew, "eligible quote snapshot exceeds maximum input skew")
    offers = tuple(Offer(s.observation_id,contract_id,family+'_lay' if s.outcome_id in lay_mapping else family,
                         lay_mapping.get(s.outcome_id,s.outcome_id),s.sportsbook_id,s.decimal_odds,commissions[s.sportsbook_id])
                   for s in eligible)
    return CalculationInputs(contract,offers,streams)

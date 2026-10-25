"""Deterministic fixture repository and application service, never a live fallback.

All calculations delegate to the existing pure backend. The fixture explicitly
binds complete selections, matching rules, reference books and quote identities.
"""
from corner.additional_markets import LINE_MARKETS, SPREAD_MARKETS, TOTAL_MARKETS, coordinate, PROP_KEYS
from dataclasses import is_dataclass, fields
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import threading
from pathlib import Path

from corner.featured_tools import MatchedMarket, Offer, ToolInputError, calculate_back_cover, calculate_back_lay
from corner.featured_ev import calculate_featured_ev
from corner.reference_policy import sufficient_references
from corner.featured_middles import LineBet, calculate_middle, find_middles
from corner.featured_promos import PromoTerms, convert_promo, convert_promo_back_hedge
from api.models import Game, Book, Quote, EVRow, CoverRow, MiddleRow, Meta, PromoResponse

FIXTURE = Path(__file__).resolve().parents[1] / 'fixtures/product_api/v1/catalog.json'
D = Decimal


def wire(value):
    if value is None or type(value) in (str, int, bool):
        return value
    if isinstance(value, Decimal):
        return format(value, 'f')
    if is_dataclass(value):
        return {field.name: wire(getattr(value, field.name)) for field in fields(value)}
    if hasattr(value, 'model_dump'):
        return value.model_dump(mode='json')
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    if isinstance(value, dict):
        return {key: wire(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [wire(item) for item in value]
    if value is None or type(value) in (str, int, bool):
        return value
    raise TypeError(f'unsupported API serialization: {type(value).__name__}')


def _json_default(value):
    # Let the JSON encoder traverse ordinary containers/primitives in C rather
    # than recursively copying every result tree in Python before encoding.
    if isinstance(value, Decimal):
        return format(value, 'f')
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    if is_dataclass(value):
        return {field.name: getattr(value, field.name) for field in fields(value)}
    if hasattr(value, 'model_dump'):
        return value.model_dump(mode='json')
    raise TypeError(f'unsupported API serialization: {type(value).__name__}')


def digest(value):
    return hashlib.sha256(json.dumps(value, default=_json_default, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate fixture field')
        result[key] = value
    return result


def _verify_selections(contract, game):
    """Fixture declarations are explicit, but still must be internally coherent."""
    selections, key = contract['selections'], contract['market_key']
    sides = [s['side'] for s in selections]
    if key in {'h2h', 'outrights', 'draw_no_bet', 'btts'} or key in PROP_KEYS and selections[0]['point'] is None:
        if any(s['point'] is not None for s in selections):
            raise ValueError('winner markets cannot contain lines')
        if key == 'btts' or key in PROP_KEYS:
            if set(sides) != {'yes','no'} or len(sides) != 2:
                raise ValueError('BTTS requires yes and no')
        elif key in {'h2h', 'draw_no_bet'}:
            if set(sides) not in ({'home', 'away'}, {'home', 'away', 'draw'}) or len(sides) != len(set(sides)):
                raise ValueError('invalid h2h selection structure')
            if key == 'draw_no_bet' and (set(sides) != {'home','away'} or not contract.get('refund_possible')):
                raise ValueError('Draw No Bet requires a draw refund branch')
            if {s['name'] for s in selections if s['side'] != 'draw'} != set(game['participants']):
                raise ValueError('h2h participants mismatch')
        elif any(side != 'entrant' for side in sides) or sorted(s['name'] for s in selections) != sorted(game['participants']):
            raise ValueError('incomplete outright fixture field')
    else:
        from fractions import Fraction
        points = [D(s['point']) for s in selections]
        if len(points) != 2 or any(not p.is_finite() or (Fraction(p) * 2).denominator != 1 for p in points):
            raise ValueError('exact integer/half-line fixture contract required')
        if key in SPREAD_MARKETS:
            if set(sides) != {'home', 'away'} or sum(map(Fraction, points)) != 0:
                raise ValueError('spread selections must be exact opposite lines')
            if {s['name'] for s in selections} != set(game['participants']):
                raise ValueError('spread participants mismatch')
        elif set(sides) != {'over', 'under'} or points[0] != points[1] or points[0] < 0:
            raise ValueError('total selections must share one nonnegative line')
    if key in {'team_totals', 'alternate_team_totals'} and contract.get('subject') not in game['participants']:
        raise ValueError('team total participant mismatch')
    if game['scope'] != ('competition' if key == 'outrights' else 'full_game'):
        raise ValueError('fixture market/game scope mismatch')


def D_TS(text, captured_at):
    value = datetime.fromisoformat(text.replace('Z', '+00:00'))
    if value.utcoffset() is None or value > captured_at:
        raise ValueError('invalid quote observation time')
    return value


DATABASE_WARNINGS = ('retained_provider_quotes_not_live', 'availability_unverified',
                     'settlement_rules_assumed_equivalent', 'no_production_authorization',
                     'unverified_fee_quotes_excluded_from_financial_tools')


# find_middles is a pure function of its bets, so a game whose lines and prices did not change since the last
# catalog build reuses the earlier result. The calculation itself is untouched.
_MIDDLES = {}
_MIDDLES_MAX = 4096
# Whether two lines leave a window where both bets win depends only on their sides and lines, never on odds,
# stakes or books. It is answered by the real calculate_middle on a probe pair and remembered per line pair.
_WINDOWS = {}
_WINDOWS_MAX = 8192
# find_middles refuses a game above these sizes; the pre-filter must not hide that refusal.
_MIDDLE_MAX_BETS = 2000
_MIDDLE_MAX_PAIRS = find_middles.__kwdefaults__['maximum_pair_checks']


def _has_window(first, second, refund_possible):
    key = (first.market_key, first.side, first.line, second.side, second.line, refund_possible)
    found = _WINDOWS.get(key)
    if found is None:
        def probe(bet, name):
            return LineBet(f'probe:{name}', f'probe-book-{name}', 'probe', bet.market_key, bet.side, bet.line, D(2), D(100), D(0))
        found = bool(calculate_middle(contract_id='probe', first=probe(first, 'a'), second=probe(second, 'b'),
                                      refund_possible=refund_possible).double_win_ranges)
        if len(_WINDOWS) >= _WINDOWS_MAX:
            _WINDOWS.pop(next(iter(_WINDOWS)))
        _WINDOWS[key] = found
    return found


def _windowed(game_bets, refund_possible):
    """The bets that can be half of a double-win pair, or all of them when find_middles must see the whole game.

    find_middles only returns pairs with a window, so dropping a bet that has no windowed partner cannot change
    its result, but it skips the exact payoff arithmetic for the (large) majority of pairs.
    """
    groups = {}
    for bet in game_bets:
        high, low = groups.setdefault((bet.contract_id, bet.market_key), ([], []))
        (high if bet.side in {'home', 'over'} else low).append(bet)
    if len(game_bets) > _MIDDLE_MAX_BETS or sum(len(h) * len(l) for h, l in groups.values()) > _MIDDLE_MAX_PAIRS:
        return game_bets
    keep = set()
    for high, low in groups.values():
        for first in high:
            for second in low:
                if first.sportsbook_id != second.sportsbook_id and _has_window(first, second, refund_possible):
                    keep.add(first.quote_id)
                    keep.add(second.quote_id)
    return [bet for bet in game_bets if bet.quote_id in keep]


def _middles_for(game_bets, refund_possible):
    key = (tuple(game_bets), refund_possible)
    found = _MIDDLES.get(key)
    if found is None:
        found = find_middles(_windowed(game_bets, refund_possible), refund_possible=refund_possible)
        if len(_MIDDLES) >= _MIDDLES_MAX:
            _MIDDLES.pop(next(iter(_MIDDLES)))
        _MIDDLES[key] = found
    return found


class APIProblem(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class SnapshotMemo(dict):
    """Bounded single-flight calculations shared by concurrent snapshot readers."""
    def __init__(self):
        super().__init__()
        self.lock=threading.RLock()

    def get_or_create(self,key,build):
        with self.lock:
            found=self.get(key)
            if found is not None:return found
            found=build()
            if len(self)>=256:self.clear()
            self[key]=found
            return found


class FixtureCatalog:
    def __init__(self, path=FIXTURE, *, raw=None):
        if raw is None:
            raw = json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=_unique_object)
        self.data_mode = raw.get('data_mode', 'fixture')
        if self.data_mode not in ('fixture', 'database'):
            raise ValueError('unsupported data mode')
        if raw['format'] != 'corner.product_fixture/1':
            raise ValueError('unsupported fixture format')
        self.captured_at = datetime.fromisoformat(raw['captured_at'].replace('Z', '+00:00'))
        self.observed_at = datetime.fromisoformat(raw['observed_at'].replace('Z', '+00:00'))
        if self.captured_at.utcoffset() is None or self.observed_at.utcoffset() is None or self.observed_at > self.captured_at:
            raise ValueError('invalid fixture capture chronology')
        from corner.book_policy import supported_book
        self.books = tuple(Book.model_validate(book) for book in raw['books'] if supported_book(book['id']))
        book_map = {b.id: b for b in self.books}
        if len(book_map) != len(self.books):
            raise ValueError('duplicate fixture book')
        self.contracts, self.offers, self.quote_map = {}, {}, {}
        game_meta = {game['id']: game for game in raw['games']}
        if len(game_meta) != len(raw['games']):
            raise ValueError('duplicate fixture game')
        self.game_for_contract = {}
        references = tuple(b for b in raw['required_reference_books'] if supported_book(b))
        targets = {b for b in raw['target_books'] if supported_book(b)}
        if not targets or not targets <= book_map.keys() or (self.data_mode != 'database' and targets.intersection(references)):
            raise ValueError('invalid target/reference routing')
        line_bets, rows = [], []
        self._ev_inputs = []
        for contract in raw['contracts']:
            key, game_id, contract_id = contract['market_key'], contract['game_id'], contract['id']
            if contract_id in self.contracts or game_id not in game_meta:
                raise ValueError('duplicate or unbound fixture contract')
            selections = contract['selections']
            # A refund (push) branch only exists on whole-number spread/total lines; the per-contract flag lets
            # half-point lines and moneylines show their true locked-in profit instead of a floor of zero.
            refund = contract.get('refund_possible', raw['refund_possible'])
            market = MatchedMarket(contract_id, key, tuple(s['id'] for s in selections), refund)
            _verify_selections(contract, game_meta[game_id])
            if key in LINE_MARKETS and any(D(s['point']) == D(s['point']).to_integral_value() for s in selections) and not market.refund_possible:
                raise ValueError('integer lines require explicit push/refund branch')
            self.contracts[contract_id] = market
            self.game_for_contract[contract_id] = game_id
            current = []
            for direction, prices in ((key, contract['prices']), (key + '_lay', contract['lay_prices'])):
                for book_id, odds in prices.items():
                    if not supported_book(book_id):
                        continue
                    if len(odds) != len(selections):
                        raise ValueError('incomplete fixture price population')
                    book_links = contract.get('links', {}).get(book_id)
                    for position, (selection, price) in enumerate(zip(selections, odds)):
                        if price is None and self.data_mode == 'database' and key in PROP_KEYS:
                            continue
                        quote_id = f'{contract_id}:{book_id}:{direction}:{selection["id"]}'
                        offer = Offer(quote_id, contract_id, direction, selection['id'], book_id, D(price), D(book_map[book_id].commission or 0))
                        fee_known = book_map[book_id].fee_status in {'modeled', 'fixture_explicit'}
                        if fee_known:
                            self.offers[quote_id] = offer
                        current.append(offer)
                        self.quote_map[quote_id] = Quote(id=quote_id, game_id=game_id, contract_id=contract_id, market_key=direction,
                            sportsbook_id=book_id, selection_id=selection['id'], selection_name=selection['name'], side=selection['side'],
                            fee_status=book_map[book_id].fee_status,
                            point=selection['point'], decimal_odds=price, commission_rate=book_map[book_id].commission,
                            observed_at=D_TS(contract.get('observed', {}).get(book_id, raw['observed_at']), self.captured_at),
                            provider_updated_at=None,
                            links=book_links[position] if book_links and direction == key else None,
                            source_ids=(contract.get('source_ids', {}).get(book_id) or [None] * len(selections))[position] if direction == key else None,
                            evidence_kind='retained_provider_quote' if self.data_mode == 'database' else 'synthetic_fixture')
                        if key in LINE_MARKETS and fee_known:
                            family = coordinate(key)
                            subject = contract.get('subject', '')
                            if key in PROP_KEYS:
                                subject += ':' + key.removesuffix('_alternate')
                            shared = f'{game_id}:{family}:{subject}:{raw["settlement_identity"]}'
                            line_bets.append(LineBet(quote_id, book_id, shared, family, selection['side'], D(selection['point']),
                                                     D(price), D(100), D(book_map[book_id].commission)))
            back = [o for o in current if o.market_key == key]
            refs = [o for o in back if o.sportsbook_id in references]
            full = tuple(r for r in references if sum(o.sportsbook_id == r for o in refs) == len(selections))
            # Fixtures need every named reference; database mode uses whichever eligible books fully price this contract (min 2).
            used = full if self.data_mode == 'database' else references
            sport_key = game_meta[game_id]['sport_key']
            complete_refs = sufficient_references(full, sport_key) if self.data_mode == 'database' else len(full) == len(references)
            refs = [o for o in refs if o.sportsbook_id in used]
            for target in (o for o in current if key not in PROP_KEYS and o.sportsbook_id in targets and complete_refs and o.quote_id in self.offers):
                target_used = tuple(b for b in used if b != target.sportsbook_id)
                target_refs = [o for o in refs if o.sportsbook_id in target_used]
                if not sufficient_references(target_used, sport_key):
                    continue
                self._ev_inputs.append((market, target, tuple(target_refs), target_used, sport_key))
                result = calculate_featured_ev(market, target, target_refs, required_reference_books=target_used, stake=D(100), sport_key=sport_key)
                if result.conditional_ev_ratio_on_capital > 0:
                    ids = [target.quote_id] + [o.quote_id for o in target_refs]
                    rows.append(EVRow(**self._row(game_id, contract_id, target.market_key, ids, 'positive_ev', result,
                                                 result.capital_at_risk, ev=result.conditional_ev_ratio_on_capital), calculation=result))
            executable = [o for o in back if o.quote_id in self.offers]
            if {o.selection_id for o in executable} == set(market.selection_ids):
                cover = calculate_back_cover(market, executable, total_stake=D(200))
                ids = [leg.quote_id for leg in cover.legs]
                for kind in ('arbitrage', 'low_hold'):
                    if kind == 'low_hold' or (cover.decisive_arbitrage and len(selections) == 2):
                        rows.append(CoverRow(kind=kind, **self._row(game_id, contract_id, key, ids, kind, cover, cover.total_stake,
                                                                  minimum=cover.minimum_modeled_profit), calculation=cover))
            for lay in (o for o in current if o.market_key.endswith('_lay') and o.quote_id in self.offers):
                for target in (o for o in executable if o.selection_id == lay.selection_id):
                    hedge = calculate_back_lay(market, target, lay, back_stake=D(100))
                    ids = [target.quote_id, lay.quote_id]
                    for kind in ('arbitrage', 'low_hold'):
                        if kind == 'low_hold' or (hedge.minimum_decisive_profit > 0 and len(selections) == 2):
                            rows.append(CoverRow(kind=kind, **self._row(game_id, contract_id, lay.market_key, ids, kind, hedge,
                                hedge.conservative_capital_required, minimum=hedge.minimum_modeled_profit), calculation=hedge))
        by_game = {}
        for bet in line_bets:
            by_game.setdefault(bet.contract_id, []).append(bet)
        middles = []
        for game_bets in by_game.values():
            try:
                if self.quote_map[game_bets[0].quote_id].market_key in PROP_KEYS:
                    from corner.prop_tools import best_middles
                    cache_key = (tuple(game_bets), raw['refund_possible'])
                    found = _MIDDLES.get(cache_key)
                    if found is None:
                        found = best_middles(game_bets, raw['refund_possible'])
                        if len(_MIDDLES) >= _MIDDLES_MAX:
                            _MIDDLES.pop(next(iter(_MIDDLES)))
                        _MIDDLES[cache_key] = found
                    middles.extend(found)
                else:
                    middles.extend(_middles_for(game_bets, raw['refund_possible']))
            except ToolInputError:
                if self.data_mode == 'fixture':
                    raise
        for result in middles:
            ids = [leg.quote_id for leg in result.legs]
            quote = self.quote_map[ids[0]]
            rows.append(MiddleRow(**self._row(quote.game_id, result.contract_id, quote.market_key, ids, 'middle', result,
                                result.payoff.conservative_capital_required, minimum=result.payoff.minimum_modeled_profit), calculation=result))
        self.rows = tuple(rows)
        self.quotes = tuple(sorted(self.quote_map.values(), key=lambda q: q.id))
        by_game_quotes = {}
        for q in self.quotes:
            by_game_quotes.setdefault(q.game_id, []).append(q)
        self.quotes_by_game = {game_id: tuple(items) for game_id, items in by_game_quotes.items()}
        self.games = tuple(Game(**game, market_keys=sorted({q.market_key for q in by_game_quotes.get(game['id'], ())}),
                               quote_count=len(by_game_quotes.get(game['id'], ()))) for game in raw['games'])
        # Sorted and filtered result lists, valid for this immutable snapshot only: a rebuild replaces the whole catalog.
        self.memo = SnapshotMemo()
        self.game_map = {game.id: game for game in self.games}
        # Snapshot covers data AND calculated output, so pagination clients notice
        # changed calculator output after a deploy even if fixture bytes are equal.
        self.snapshot_id = self.data_mode + ':' + digest(dict(source=raw, games=self.games, quotes=self.quotes, rows=self.rows))

    def ev_rows(self, method):
        if method == 'current':
            return [row for row in self.rows if row.kind == 'positive_ev']
        cache_key = ('devig_rows', method)
        return self.memo.get_or_create(cache_key,lambda:self._build_ev_rows(method))

    def _build_ev_rows(self,method):
        rows = []
        for market, target, refs, books, sport in self._ev_inputs:
            try:
                result = calculate_featured_ev(market, target, refs, required_reference_books=books,
                                              stake=D(100), sport_key=sport, devig_method=method)
            except ToolInputError as error:
                if str(error) == 'devig method unavailable for reference population':
                    continue
                raise
            if result.conditional_ev_ratio_on_capital <= D('1e-20'):
                continue
            ids = [target.quote_id] + [o.quote_id for o in refs]
            rows.append(EVRow(**self._row(self.game_for_contract[market.contract_id], market.contract_id,
                target.market_key, ids, 'positive_ev', result, result.capital_at_risk,
                ev=result.conditional_ev_ratio_on_capital), calculation=result))
        return tuple(rows)

    def _row(self, game_id, contract, key, ids, kind, result, capital, minimum=None, ev=None):
        return dict(id=f'{kind}:' + digest(result), game_id=game_id, contract_id=contract, market_key=key,
                    sportsbook_ids=sorted({self.quote_map[i].sportsbook_id for i in ids}), quote_ids=ids,
                    oldest_observed_at=min(self.quote_map[i].observed_at for i in ids),
                    conditional_ev_ratio=None if ev is None else format(ev, 'f'),
                    minimum_profit=None if minimum is None else format(minimum, 'f'), capital_required=format(capital, 'f'))

    def meta(self):
        extra = {'warnings': DATABASE_WARNINGS} if self.data_mode == 'database' else {}
        return Meta(data_mode=self.data_mode, snapshot_id=self.snapshot_id, captured_at=self.captured_at,
                    reference_clock_at=self.captured_at, served_at=datetime.now(timezone.utc), **extra)

    def verify_snapshot(self, supplied):
        if supplied is not None and supplied != self.snapshot_id:
            raise APIProblem(409, 'snapshot_changed', 'Reload the snapshot before continuing.')

    def game(self, game_id):
        if game_id not in self.game_map:
            raise APIProblem(404, 'game_not_found', 'Game was not found in this snapshot.')
        return self.game_map[game_id]

    def promo(self, request):
        self.verify_snapshot(request.snapshot_id)
        market = self.contracts.get(request.contract_id)
        promo, hedge = self.offers.get(request.promo_quote_id), self.offers.get(request.hedge_quote_id)
        if market is None or promo is None or hedge is None:
            raise APIProblem(404, 'quote_or_contract_not_found', 'Select quotes and a contract from this snapshot.')
        values = request.terms.model_dump()
        for field in ('face_value', 'eligible_stake_cap', 'minimum_decimal_odds', 'loss_refund_cap'):
            values[field] = D(values[field])
        terms = PromoTerms(**values)
        stake_limit = None if request.maximum_hedge_stake is None else D(request.maximum_hedge_stake)
        if request.hedge_type == 'lay':
            result = convert_promo(market, promo, hedge, terms, stake_increment=D(request.stake_increment),
                                   maximum_lay_stake=stake_limit,
                                   maximum_lay_liability=None if request.maximum_lay_liability is None else D(request.maximum_lay_liability))
        else:
            if request.maximum_lay_liability is not None:
                raise ToolInputError('lay liability cap is not applicable to an opposite-back hedge')
            result = convert_promo_back_hedge(market, promo, hedge, terms, stake_increment=D(request.stake_increment),
                                              maximum_hedge_stake=stake_limit)
        return PromoResponse(id='promo:' + digest(dict(snapshot=self.snapshot_id, command=request, result=result)),
                             game_id=self.game_for_contract[market.contract_id], contract_id=market.contract_id,
                             promo_quote_id=promo.quote_id, hedge_quote_id=hedge.quote_id, calculation=result)


def ordered(items, query, numeric_fields=()):
    """Sort exact decimal values, stable ID tie-break, nulls always last."""
    items = sorted(items, key=lambda item: item.id)
    defined = [item for item in items if getattr(item, query.sort) is not None]
    missing = [item for item in items if getattr(item, query.sort) is None]
    key = (lambda item: D(getattr(item, query.sort))) if query.sort in numeric_fields else (lambda item: getattr(item, query.sort))
    return sorted(defined, key=key, reverse=query.descending) + missing


def paginate(items, query, numeric_fields=(), *, memo=None, memo_key=None):
    """One page of `ordered` items.

    With a memo (the snapshot's own dict) and a key naming the filter, `items` is a function that builds the
    filtered list. The ordered list is then built once and every further page of it is just a slice.
    """
    if memo is None:
        items = ordered(items, query, numeric_fields)
    else:
        key = (memo_key, query.sort, query.descending)
        if hasattr(memo,'get_or_create'):
            items=memo.get_or_create(key,lambda:ordered(items(),query,numeric_fields))
        else:
            cached = memo.get(key)
            if cached is None:
                cached = ordered(items(), query, numeric_fields)
                if len(memo) >= 256:
                    memo.clear()
                memo[key] = cached
            items = cached
    end = query.offset + query.limit
    return dict(items=items[query.offset:end], total=len(items), offset=query.offset, limit=query.limit,
                next_offset=end if end < len(items) else None)

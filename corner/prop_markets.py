"""Player-prop market catalog, payload normalization and sharp-price EV calculation.

Pure functions only: no network, no database. Prop quotes are kept apart from the strict
featured (h2h/spreads/totals) pipeline because they are priced per player and per line.
"""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN
import os

from corner.links import clean_links
from corner.native_ids import native_ids
from corner.book_policy import supported_book, supported_books
from corner.reference_policy import sufficient_references
from corner.reference_weights import normalized_reference_weights, WEIGHT_VERSION
from corner.market_width import widest_market_width
from corner.pricing import fee_policy, reference_eligible, no_vig_pair, VERSION as PRICING_VERSION

# Same reference books (and environment override) as the main +EV feed in api/database.py.
SHARP_BOOKS = frozenset(supported_books(b.strip() for b in os.environ.get('CORNER_TOOLS_REFERENCE_BOOKS', '').split(',')
                        if b.strip())) or frozenset({'pinnacle', 'betfair_ex_uk', 'prophetx', 'kalshi', 'betopenly', 'polymarket'})
MIN_SHARPS = 2  # the +EV feed requires at least two sharp books fully pricing the line
# Books that also count as a reference for player props only. They still appear as bets: a book's own bet is
# priced against the other reference books, never against itself.
PROP_EXTRA_SHARPS = frozenset({'fanduel', 'prizepicks', 'underdog', 'novig'})
PROP_SHARP_BOOKS = SHARP_BOOKS | PROP_EXTRA_SHARPS
# Over/Under or Yes/No priced on both sides ('two_way'), or a Yes-only / winner list ('yes_only').
TWO_WAY, YES_ONLY = 'two_way', 'yes_only'


@dataclass(frozen=True)
class PropMarket:
    key: str
    label: str
    group: str
    kind: str = TWO_WAY
    sides: tuple = ('Over', 'Under')


def _ou(key, label, group):
    return PropMarket(key, label, group)


def _yn(key, label, group):
    return PropMarket(key, label, group, TWO_WAY, ('Yes', 'No'))


def _yes(key, label, group):
    return PropMarket(key, label, group, YES_ONLY, ('Yes', 'No'))


FAMILIES = {
    'basketball': (
        _ou('player_points', 'Points', 'Scoring'),
        _ou('player_points_q1', '1st Quarter Points', 'Scoring'),
        _ou('player_threes', 'Made Threes', 'Scoring'),
        _ou('player_rebounds', 'Rebounds', 'Rebounds & assists'),
        _ou('player_rebounds_q1', '1st Quarter Rebounds', 'Rebounds & assists'),
        _ou('player_assists', 'Assists', 'Rebounds & assists'),
        _ou('player_assists_q1', '1st Quarter Assists', 'Rebounds & assists'),
        _ou('player_blocks', 'Blocks', 'Defense & turnovers'),
        _ou('player_steals', 'Steals', 'Defense & turnovers'),
        _ou('player_turnovers', 'Turnovers', 'Defense & turnovers'),
        _ou('player_points_rebounds_assists', 'Points + Rebounds + Assists', 'Combos'),
        _ou('player_points_assists', 'Points + Assists', 'Combos'),
        _ou('player_points_rebounds', 'Points + Rebounds', 'Combos'),
        _ou('player_rebounds_assists', 'Rebounds + Assists', 'Combos'),
        _yn('player_double_double', 'Double-Double', 'Milestones'),
        _yn('player_triple_double', 'Triple-Double', 'Milestones'),
    ),
    'football': (
        _ou('player_pass_yds', 'Passing Yards', 'Passing'),
        _ou('player_pass_tds', 'Passing TDs', 'Passing'),
        _ou('player_pass_completions', 'Pass Completions', 'Passing'),
        _ou('player_pass_attempts', 'Pass Attempts', 'Passing'),
        _ou('player_pass_interceptions', 'Interceptions Thrown', 'Passing'),
        _ou('player_pass_longest_completion', 'Longest Completion', 'Passing'),
        _ou('player_rush_yds', 'Rushing Yards', 'Rushing'),
        _ou('player_rush_attempts', 'Rush Attempts', 'Rushing'),
        _ou('player_rush_longest', 'Longest Rush', 'Rushing'),
        _ou('player_receptions', 'Receptions', 'Receiving'),
        _ou('player_reception_yds', 'Receiving Yards', 'Receiving'),
        _ou('player_reception_longest', 'Longest Reception', 'Receiving'),
        _ou('player_kicking_points', 'Kicking Points', 'Kicking'),
        _ou('player_field_goals', 'Field Goals Made', 'Kicking'),
        _yes('player_anytime_td', 'Anytime TD Scorer', 'Touchdown scorers'),
        _yes('player_1st_td', 'First TD Scorer', 'Touchdown scorers'),
        _yes('player_last_td', 'Last TD Scorer', 'Touchdown scorers'),
        _ou('player_tackles_assists', 'Tackles + Assists', 'Defense'),
        _ou('player_solo_tackles', 'Solo Tackles', 'Defense'),
        _ou('player_sacks', 'Sacks', 'Defense'),
    ),
    'baseball': (
        _ou('batter_hits', 'Batter Hits', 'Batting'),
        _ou('batter_runs_scored', 'Batter Runs Scored', 'Batting'),
        _ou('batter_rbis', 'Batter RBIs', 'Batting'),
        _ou('batter_home_runs', 'Batter Home Runs', 'Batting'),
        _ou('batter_total_bases', 'Batter Total Bases', 'Batting'),
        _ou('batter_singles', 'Batter Singles', 'Batting'),
        _ou('batter_doubles', 'Batter Doubles', 'Batting'),
        _ou('batter_triples', 'Batter Triples', 'Batting'),
        _ou('batter_walks', 'Batter Walks', 'Batting'),
        _ou('batter_stolen_bases', 'Stolen Bases', 'Batting'),
        _ou('batter_hits_runs_rbis', 'Hits + Runs + RBIs', 'Batting'),
        _ou('pitcher_strikeouts', 'Pitcher Strikeouts', 'Pitching'),
        _ou('pitcher_hits_allowed', 'Pitcher Hits Allowed', 'Pitching'),
        _ou('pitcher_earned_runs', 'Pitcher Earned Runs', 'Pitching'),
        _ou('pitcher_walks', 'Pitcher Walks', 'Pitching'),
        _ou('pitcher_outs', 'Pitcher Outs Recorded', 'Pitching'),
        _yn('pitcher_record_a_win', 'Pitcher to Record a Win', 'Pitching'),
    ),
    'hockey': (
        _ou('player_points', 'Points', 'Skaters'),
        _ou('player_goals', 'Goals', 'Skaters'),
        _ou('player_assists', 'Assists', 'Skaters'),
        _ou('player_shots_on_goal', 'Shots on Goal', 'Skaters'),
        _ou('player_power_play_points', 'Power Play Points', 'Skaters'),
        _ou('player_blocked_shots', 'Blocked Shots', 'Skaters'),
        _ou('player_total_saves', 'Goalie Saves', 'Goalies'),
        _yes('player_goal_scorer_anytime', 'Anytime Goal Scorer', 'Goal scorers'),
        _yes('player_goal_scorer_first', 'First Goal Scorer', 'Goal scorers'),
        _yes('player_goal_scorer_last', 'Last Goal Scorer', 'Goal scorers'),
    ),
    'soccer': (
        _yes('player_goal_scorer_anytime', 'Anytime Goal Scorer', 'Goal scorers'),
        _yes('player_goal_scorer_first', 'First Goal Scorer', 'Goal scorers'),
        _yes('player_goal_scorer_last', 'Last Goal Scorer', 'Goal scorers'),
        _ou('player_shots', 'Shots', 'Shooting & passing'),
        _ou('player_shots_on_target', 'Shots on Target', 'Shooting & passing'),
        _ou('player_assists', 'Assists', 'Shooting & passing'),
        _yes('player_to_receive_card', 'To Receive a Card', 'Discipline'),
        _yes('player_to_receive_red_card', 'To Receive a Red Card', 'Discipline'),
    ),
}
# Credit control: only these are fetched unless the user picks others.
DEFAULT_MARKETS = {
    'basketball': ('player_points', 'player_rebounds', 'player_assists'),
    'football': ('player_pass_yds', 'player_rush_yds', 'player_reception_yds'),
    'baseball': ('batter_hits', 'pitcher_strikeouts'),
    'hockey': ('player_goals', 'player_shots_on_goal'),
    'soccer': ('player_goal_scorer_anytime', 'player_shots'),
}
PREFIX_FAMILY = (('basketball_', 'basketball'), ('americanfootball_', 'football'),
                 ('baseball_', 'baseball'), ('icehockey_', 'hockey'), ('soccer_', 'soccer'))
LABEL_BY_KEY = {m.key: m for markets in FAMILIES.values() for m in markets}


def family(sport_key):
    for prefix, name in PREFIX_FAMILY:
        if sport_key.startswith(prefix):
            return name
    return None


def markets_for(sport_key):
    return FAMILIES.get(family(sport_key), ())


def market_meta(sport_key, key):
    return next((m for m in markets_for(sport_key) if m.key == key), None)


def catalog_view(sport_keys):
    """Per-sport market list for the UI, with the credit-safe default flagged."""
    out = {}
    for sport in sport_keys:
        fam = family(sport)
        if fam:
            out[sport] = [{'key': m.key, 'label': m.label, 'group': m.group, 'kind': m.kind,
                           'default': m.key in DEFAULT_MARKETS[fam]} for m in FAMILIES[fam]]
    return out


def normalize_event(event, market_key, meta, book_filter=None):
    """Flatten one event-odds payload for one market into quote dicts.

    Skips (never invents) anything it cannot attribute to a named player and side.
    """
    quotes = []
    for book in event.get('bookmakers', []):
        if not supported_book(book['key']):
            continue
        if book_filter and book['key'] not in book_filter:
            continue
        for market in book.get('markets', []):
            if market.get('key') != market_key:
                continue
            for o in market.get('outcomes', []):
                price, name = o.get('price'), str(o.get('name') or '').strip()
                player = str(o.get('description') or '').strip()
                if price is None or Decimal(str(price)) <= 1:
                    continue
                if player:
                    side = {m.lower(): i for i, m in enumerate(meta.sides)}.get(name.lower())
                    if side is None:
                        continue
                elif meta.kind == YES_ONLY and name and name.lower() not in ('over', 'under', 'yes', 'no'):
                    player, side = name, 0
                else:
                    continue
                point = o.get('point')
                if meta.sides[0] == 'Over' and point is None:
                    continue
                # Event, market and betslip links (when the sportsbook provides them), checked before they are kept.
                links = clean_links(book['key'], book.get('link'), market.get('link'), o.get('link'))
                quotes.append({'book': book['key'], 'player': player, 'side': side,
                               **({'links': links} if links else {}),
                               'point': None if point is None else str(Decimal(str(point))),
                               'price': str(Decimal(str(price))),
                               'updated_at': market.get('last_update') or book.get('last_update')})
                quotes[-1]['source_ids'] = native_ids(book['key'], event=book.get('sid'), market=market.get('sid'),
                                                     outcome=o.get('sid'), link=(links or {}).get('outcome'))
    return quotes


def _prob(price):
    return Decimal(1) / Decimal(price)


def _sharp_side_probability(prices, side, exclude=None, sport_key=''):
    """Weighted power no-vig estimate from complete binary reference populations."""
    used = sorted(b for b, p in prices.items() if b in PROP_SHARP_BOOKS and b != exclude
                  and reference_eligible(b) and set(p) == {0, 1})
    valid = []
    for book in used:
        try:
            no_vig_pair(prices[book][0], prices[book][1])
            valid.append(book)
        except (ValueError, ArithmeticError):
            continue
    used = valid
    if not sufficient_references(used, sport_key, player_props=True):
        return None, []
    weights = normalized_reference_weights(used, sport_key, player_props=True)
    fair = sum(no_vig_pair(prices[b][0], prices[b][1])[0][side] * weights[b] for b in used)
    return fair, used


def _fair_first_side(prices, exclude=None, sport_key=''):
    return _sharp_side_probability(prices, 0, exclude, sport_key)


def _q(value):
    rounded = value.quantize(Decimal('0.000001'), ROUND_HALF_EVEN)
    return str(abs(rounded) if rounded == 0 else rounded)


def build_bets(events):
    """events: {event_id: {meta, markets:{market_key:{quotes:[...]}}}} -> one bet per soft-book side.

    Two other eligible books must each quote both sides of the same player/line.
    Remove margin per book before pooling existing reputation weights. Target is
    excluded. One-sided and DFS-only prices do not identify standalone fair odds.
    """
    bets = []
    for event_id, ev in events.items():
        sport = ev['sport_key']
        for market_key, stored in ev['markets'].items():
            meta = market_meta(sport, market_key)
            if not meta or meta.kind != TWO_WAY:
                continue
            grouped = {}
            conflicts = set()
            for q in stored['quotes']:
                if not supported_book(q['book']):
                    continue
                try:
                    price = Decimal(q['price'])
                    if not price.is_finite() or price <= 1 or price > Decimal('1e12'):
                        continue
                    if q['side'] not in (0, 1):
                        continue
                except (ValueError, ArithmeticError):
                    continue
                group = (q['player'], q['point'])
                cell = grouped.setdefault(group, {}).setdefault(q['book'], {})
                if q['side'] in cell:
                    conflicts.add((group, q['book']))
                cell[q['side']] = q
            for (player, point), by_book in grouped.items():
                by_book = {b: sides for b, sides in by_book.items() if ((player, point), b) not in conflicts}
                prices = {b: {s: Decimal(q['price']) for s, q in sides.items()} for b, sides in by_book.items()}
                # Infer no push mass from prices: integer lines are decisive-settlement conditional.
                conditional = point is not None and Decimal(point) == Decimal(point).to_integral_value()
                for book, sides in sorted(prices.items()):
                    policy = fee_policy(book)
                    if policy.commission is None:
                        continue
                    for side, price in sorted(sides.items()):
                        win, used = _sharp_side_probability(prices, side, exclude=book, sport_key=sport)
                        if win is None:
                            continue
                        weights = normalized_reference_weights(used, sport, player_props=True)
                        proportional = sum(no_vig_pair(prices[b][0], prices[b][1])[1][side] * weights[b] for b in used)
                        lower = min(win, proportional)
                        net_odds = 1 + (price-1) * (1-policy.commission)
                        bets.append({
                            'id': f'{event_id}:{market_key}:{player}:{point or ""}:{book}:{side}',
                            'event_id': event_id, 'sport_key': sport, 'home': ev['home_team'],
                            'away': ev['away_team'], 'starts_at': ev['commence_time'],
                            'market_key': market_key, 'market_label': meta.label, 'group': meta.group,
                            'player': player, 'point': point, 'side': meta.sides[side], 'book': book,
                            'price': str(price), 'ev': _q(lower * net_odds - 1), 'fair_probability': _q(win),
                            'proportional_probability': _q(proportional),
                            'probability_lower': _q(lower), 'net_decimal_odds': str(net_odds),
                            'commission_rate': str(policy.commission), 'fee_basis': policy.basis,
                            'pricing_version': PRICING_VERSION, 'calibration_status': 'not_empirically_calibrated',
                            'ev_basis': 'lower_of_power_and_proportional_after_fees',
                            'settlement_basis': 'decisive_settlement_conditional' if conditional else 'binary_no_push_assumed',
                            'sharps': used,
                            'market_width_cents': widest_market_width([list(prices[b].values()) for b in used])
                            if meta.kind == TWO_WAY else None,
                            'reference_weights': {b: str(w) for b, w in normalized_reference_weights(used, sport, player_props=True).items()},
                            'reference_weight_version': WEIGHT_VERSION,
                            'probability_basis': 'weighted_power_no_vig',
                            'observed_at': by_book[book][side].get('updated_at')
                            or stored.get('captured_at'),
                            'links': by_book[book][side].get('links')})
                        bets[-1]['source_ids'] = by_book[book][side].get('source_ids')
    return bets

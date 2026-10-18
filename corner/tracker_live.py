"""Live status, player progress and result grading from ESPN's public game data.

Pure functions: matching a bet to a game, reading a box score, and deciding what a final
result means for a bet. The HTTP calls and caching live in pipelines/tracker_service.py.

Grading is only ever a suggestion the user confirms, and only for sports whose settlement rules
match the final score ESPN reports (overtime counts). Anything ambiguous returns no suggestion.
"""
from datetime import datetime, timedelta

from corner import media

ESPN = 'https://site.api.espn.com/apis/site/v2/sports'
# provider sport key -> (ESPN path, grade_from_final_score)
LEAGUES = {
    'americanfootball_nfl': ('football/nfl', True),
    'americanfootball_ncaaf': ('football/college-football', True),
    'basketball_nba': ('basketball/nba', True),
    'basketball_ncaab': ('basketball/mens-college-basketball', True),
    'basketball_wncaab': ('basketball/womens-college-basketball', True),
    'basketball_wnba': ('basketball/wnba', True),
    'baseball_mlb': ('baseball/mlb', True),
    'icehockey_nhl': ('hockey/nhl', True),
    'soccer_epl': ('soccer/eng.1', False),
    'soccer_spain_la_liga': ('soccer/esp.1', False),
    'soccer_germany_bundesliga': ('soccer/ger.1', False),
    'soccer_italy_serie_a': ('soccer/ita.1', False),
    'soccer_france_ligue_one': ('soccer/fra.1', False),
    'soccer_usa_mls': ('soccer/usa.1', False),
    'soccer_uefa_champs_league': ('soccer/uefa.champions', False),
}
MAIN_MARKETS = ('h2h', 'spreads', 'totals')

# prop market key -> (box-score group, stat keys to add up) per sport family.
# A key containing "-" or "/" is "made-attempted" and contributes its first number ("#2" reads the second).
BASKETBALL = {
    'player_points': ('', ('points',)),
    'player_rebounds': ('', ('rebounds',)),
    'player_assists': ('', ('assists',)),
    'player_threes': ('', ('threePointFieldGoalsMade-threePointFieldGoalsAttempted',)),
    'player_blocks': ('', ('blocks',)),
    'player_steals': ('', ('steals',)),
    'player_turnovers': ('', ('turnovers',)),
    'player_points_rebounds_assists': ('', ('points', 'rebounds', 'assists')),
    'player_points_assists': ('', ('points', 'assists')),
    'player_points_rebounds': ('', ('points', 'rebounds')),
    'player_rebounds_assists': ('', ('rebounds', 'assists')),
}
HOCKEY = {
    'player_goals': ('skaters', ('goals',)),
    'player_assists': ('skaters', ('assists',)),
    'player_points': ('skaters', ('goals', 'assists')),
    'player_shots_on_goal': ('skaters', ('shotsTotal',)),
    'player_blocked_shots': ('skaters', ('blockedShots',)),
    'player_total_saves': ('goalies', ('saves',)),
}
FOOTBALL = {
    'player_pass_yds': ('passing', ('passingYards',)),
    'player_pass_tds': ('passing', ('passingTouchdowns',)),
    'player_pass_completions': ('passing', ('completions/passingAttempts',)),
    'player_pass_attempts': ('passing', ('completions/passingAttempts#2',)),
    'player_pass_interceptions': ('passing', ('interceptions',)),
    'player_rush_yds': ('rushing', ('rushingYards',)),
    'player_rush_attempts': ('rushing', ('rushingAttempts',)),
    'player_rush_longest': ('rushing', ('longRushing',)),
    'player_receptions': ('receiving', ('receptions',)),
    'player_reception_yds': ('receiving', ('receivingYards',)),
    'player_reception_longest': ('receiving', ('longReception',)),
    'player_sacks': ('defensive', ('sacks',)),
    'player_solo_tackles': ('defensive', ('soloTackles',)),
    'player_tackles_assists': ('defensive', ('totalTackles',)),
    'player_field_goals': ('kicking', ('fieldGoalsMade/fieldGoalAttempts',)),
    'player_kicking_points': ('kicking', ('totalKickingPoints',)),
}
BASEBALL = {
    'batter_hits': ('batting', ('hits',)),
    'batter_runs_scored': ('batting', ('runs',)),
    'batter_rbis': ('batting', ('RBIs',)),
    'batter_home_runs': ('batting', ('homeRuns',)),
    'batter_walks': ('batting', ('walks',)),
    'batter_hits_runs_rbis': ('batting', ('hits', 'runs', 'RBIs')),
    'pitcher_strikeouts': ('pitching', ('strikeouts',)),
    'pitcher_hits_allowed': ('pitching', ('hits',)),
    'pitcher_earned_runs': ('pitching', ('earnedRuns',)),
    'pitcher_walks': ('pitching', ('walks',)),
    'pitcher_outs': ('pitching', ('fullInnings.partInnings',)),
}
GROUP_NAMES = {'skaters': ('forwards', 'defenses', 'defense', 'skaters')}
PROP_TABLES = {'basketball': BASKETBALL, 'hockey': HOCKEY, 'football': FOOTBALL, 'baseball': BASEBALL}


def espn_path(sport_key):
    entry = LEAGUES.get(sport_key)
    return entry[0] if entry else None


def family(sport_key):
    path = espn_path(sport_key)
    return path.split('/')[0] if path else None


def can_grade(sport_key):
    entry = LEAGUES.get(sport_key)
    return bool(entry and entry[1])


def supports_prop(sport_key, prop_market):
    return prop_market.removesuffix('_alternate') in PROP_TABLES.get(family(sport_key), {})


def split_matchup(text):
    parts = str(text).split(' at ')
    return (parts[0].strip(), parts[1].strip()) if len(parts) == 2 and all(p.strip() for p in parts) else None


def same_team(ours, theirs):
    """The same club under different spellings; ambiguous nicknames never match."""
    index = {media.norm(theirs): {'name': theirs}}
    return media.match_team(index, ours) is not None or media.core(media.norm(ours)) == media.core(media.norm(theirs))


def find_event(events, away, home, starts_at=None, max_hours=8):
    """The scoreboard event for this matchup, using start time to separate doubleheaders."""
    hits = []
    for event in events or []:
        sides = {c.get('homeAway'): c.get('team', {}).get('displayName', '') for c in (event.get('competitions') or [{}])[0].get('competitors', [])}
        if same_team(away, sides.get('away', '')) and same_team(home, sides.get('home', '')):
            hits.append(event)
    if len(hits) <= 1 or not starts_at:
        return hits[0] if len(hits) == 1 else None
    want = datetime.fromisoformat(starts_at.replace('Z', '+00:00'))

    def gap(event):
        try:
            return abs(datetime.fromisoformat(event['date'].replace('Z', '+00:00')) - want)
        except (KeyError, ValueError):
            return timedelta.max
    best = min(hits, key=gap)
    return best if gap(best) <= timedelta(hours=max_hours) else None


def _number(value):
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def status_view(event):
    """{'state': pre|in|post, 'detail': '4:12 - 3rd', 'score': {'away': n, 'home': n}} from a scoreboard event."""
    competition = (event.get('competitions') or [{}])[0]
    status = (competition.get('status') or event.get('status') or {})
    kind = status.get('type', {})
    score = {}
    for c in competition.get('competitors', []):
        value = _number(c.get('score'))
        score[c.get('homeAway')] = None if value is None else int(value)
    state = kind.get('state') if kind.get('state') in ('pre', 'in', 'post') else 'pre'
    if state == 'post' and not kind.get('completed', True):
        state = 'in'
    return {'state': state, 'detail': kind.get('shortDetail') or kind.get('detail') or '', 'score': score,
            'postponed': kind.get('name') in ('STATUS_POSTPONED', 'STATUS_CANCELED', 'STATUS_SUSPENDED')}


def _stat_values(group_stats):
    keys = group_stats.get('keys') or []
    return {a.get('athlete', {}).get('displayName', ''): dict(zip(keys, a.get('stats') or []))
            for a in group_stats.get('athletes', [])}


def _read(values, spec):
    """One box-score cell as a number: 'made-attempted' and 'made/attempted' read the first part; 'IP' reads outs."""
    index = 1 if spec.endswith('#2') else 0
    spec = spec.removesuffix('#2')
    raw = values.get(spec)
    if raw is None:
        return None
    if spec == 'fullInnings.partInnings':
        whole, _, part = str(raw).partition('.')
        try:
            return int(whole) * 3 + int(part or 0)
        except ValueError:
            return None
    if '-' in spec or '/' in spec:
        parts = str(raw).replace('-', '/').split('/')
        raw = parts[index] if len(parts) > index else None
    return _number(raw)


def player_stat(summary, player, sport_key, prop_market):
    """(value, label) for the player in a ESPN summary, or None when the box score cannot say."""
    prop_market = prop_market.removesuffix('_alternate')
    table = PROP_TABLES.get(family(sport_key), {})
    if prop_market not in table:
        return None
    group, specs = table[prop_market]
    wanted = GROUP_NAMES.get(group, (group,))
    found = None
    for team in (summary.get('boxscore') or {}).get('players', []):
        for stats in team.get('statistics', []):
            if group and stats.get('name') not in wanted and stats.get('type') not in wanted:
                continue
            for name, values in _stat_values(stats).items():
                if media.same_person(name, player, sport_key):
                    parts = [_read(values, spec) for spec in specs]
                    if all(p is not None for p in parts):
                        found = sum(parts)
    return None if found is None else (found, prop_market)


def result_vs_line(value, line, side):
    """'won' | 'lost' | 'push' for an over/under on a final number."""
    if value == line:
        return 'push'
    return 'won' if (value > line) == (side == 'over') else 'lost'


def grade_main(market_key, side, point, score):
    """Result of a moneyline, spread or total from the final score, or None if it cannot be decided."""
    away, home = score.get('away'), score.get('home')
    if away is None or home is None:
        return None
    if market_key == 'h2h':
        if side == 'draw':
            return 'won' if away == home else 'lost'
        if side not in ('home', 'away'):
            return None
        if away == home:
            return 'push'
        return 'won' if (home > away) == (side == 'home') else 'lost'
    if point is None:
        return None
    if market_key == 'spreads' and side in ('home', 'away'):
        margin = (home - away if side == 'home' else away - home) + point
        return 'won' if margin > 0 else 'lost' if margin < 0 else 'push'
    if market_key == 'totals' and side in ('over', 'under'):
        return result_vs_line(away + home, point, side)
    return None


def live_for_bet(bet, event, summary=None):
    """What to show for a pending bet, given its matched scoreboard event (and box score for props)."""
    ref = bet.get('ref') or {}
    view = status_view(event)
    out = {'state': view['state'], 'detail': view['detail'], 'score': view['score'], 'progress': None, 'suggest': None}
    side, point, market_key = ref.get('side'), ref.get('point'), ref.get('market_key')
    prop = ref.get('prop_market')
    if prop:
        stat = player_stat(summary, ref.get('player') or '', bet.get('sport_key', ''), prop) if summary else None
        if stat and point is not None:
            out['progress'] = {'value': stat[0], 'line': point, 'side': side}
            if view['state'] == 'post' and can_grade(bet.get('sport_key', '')) and side in ('over', 'under'):
                out['suggest'] = {'result': result_vs_line(stat[0], point, side), 'basis': f'Box score: {stat[0]:g} vs {point:g}'}
    elif market_key in MAIN_MARKETS:
        away, home = view['score'].get('away'), view['score'].get('home')
        if market_key == 'totals' and point is not None and away is not None and home is not None:
            out['progress'] = {'value': away + home, 'line': point, 'side': side}
        if view['state'] == 'post' and can_grade(bet.get('sport_key', '')) and not view['postponed']:
            result = grade_main(market_key, side, point, view['score'])
            if result:
                names = {c.get('homeAway'): c.get('team', {}).get('shortDisplayName') or c.get('team', {}).get('displayName', '')
                         for c in (event.get('competitions') or [{}])[0].get('competitors', [])}
                out['suggest'] = {'result': result, 'basis': f"Final: {names.get('away', 'Away')} {view['score'].get('away')}, {names.get('home', 'Home')} {view['score'].get('home')}"}
    if view['postponed']:
        out['detail'] = out['detail'] or 'Postponed'
    return out

"""Pregame prop research. Historical hit rates are not calibrated win probabilities."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import math

VERSION = 'prop-trends/2026-10-17.1'


def instant(value):
    try:
        at = datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return at.timestamp() if at.tzinfo else None
    except (ValueError, TypeError):
        return None


def number(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and abs(result) < 100000 else None
    except (ValueError, InvalidOperation):
        return None


def wilson(wins, count, z=1.959963984540054):
    """95% interval for historical independent Bernoulli trials, not future coverage."""
    if not count:
        return None
    p = wins/count
    denominator = 1+z*z/count
    center = (p+z*z/(2*count))/denominator
    radius = z*math.sqrt(p*(1-p)/count+z*z/(4*count*count))/denominator
    return [max(0,center-radius), min(1,center+radius)]


def summarize(games, line, side):
    values = [number(g['value']) for g in games]
    wins = sum(v>line if side=='Over' else v<line for v in values)
    pushes = sum(v==line for v in values)
    losses = len(values)-wins-pushes
    settled = wins+losses
    return {'games':len(values), 'wins':wins, 'losses':losses, 'pushes':pushes,
            'hit_rate':wins/settled if settled else None,
            'mean':float(sum(values)/len(values)) if values else None,
            'median':float(sorted(values)[len(values)//2]) if len(values)%2 else
                     float(sum(sorted(values)[len(values)//2-1:len(values)//2+1])/2) if values else None,
            'historical_interval':wilson(wins,settled)}


def analyze(games, *, line, side, price, commission, as_of, opponent='', home=None):
    """Line-specific descriptive features plus an explicitly provisional model.

    Jeffreys-smoothed decisive hit probability (w+.5)/(w+l+1). Integer pushes
    return stake, so EV includes empirical decisive frequency. Wilson sensitivity
    describes historical sampling uncertainty only. No news/ matchup multiplier
    is invented. Overlapping L1/L5/L10 windows never become independent evidence.
    """
    line, price, commission = number(line), number(price), number(commission)
    if line is None or side not in ('Over','Under') or price is None or price<=1 or commission is None or not 0<=commission<=1:
        raise ValueError('An exact over/under line and supported target fees are required.')
    unique, conflicts = {}, set()
    for game in games:
        at = instant(game.get('date'))
        value = number(game.get('value'))
        # DNP, future/uncompleted games, duplicate conflicts and unknown stats never become zero.
        if not game.get('completed') or game.get('dnp') or value is None or at is None or at>=as_of or as_of-at>366*86400:
            continue
        ident = str(game.get('id',''))
        if not ident:
            continue
        if ident in unique:
            prior = unique[ident]
            if (instant(prior.get('date')),number(prior.get('value')),prior.get('opponent'),prior.get('home'),number(prior.get('workload'))) != (at,value,game.get('opponent'),game.get('home'),number(game.get('workload'))):
                conflicts.add(ident)
        else:
            unique[ident] = game
    clean = sorted((g for i,g in unique.items() if i not in conflicts),key=lambda g:instant(g['date']),reverse=True)[:40]
    windows = {str(n):summarize(clean[:n],line,side) for n in (1,5,10,20)}
    baseline = summarize(clean[:30],line,side)
    matchup = summarize([g for g in clean if opponent and g.get('opponent')==opponent],line,side)
    venue = summarize([g for g in clean if home is not None and g.get('home') is home],line,side)
    n = baseline['wins']+baseline['losses']
    flags = ['Uncalibrated research model; recent hit rates are not a future win rate.',
             'Overlapping windows are descriptive, not independent votes.']
    if len(clean)<10:
        flags.append('Fewer than ten usable games; small-sample uncertainty is substantial.')
    if matchup['games']<5:
        flags.append('Prior matchup sample is too small to adjust the model.')
    if baseline['pushes']:
        flags.append('Pushes refund stake and are excluded from decisive hit rates.')
    if len({g.get('season') for g in clean if g.get('season')})>1:
        flags.append('History spans seasons; role and team context can change.')
    if len({g.get('team') for g in clean if g.get('team')})>1:
        flags.append('Game logs include different teams; review the player’s current role.')
        signal_context_changed = True
    else:
        signal_context_changed = False
    if clean and as_of-instant(clean[0]['date'])>30*86400:
        flags.append('Latest completed game is over 30 days old; offseason or availability context may differ.')
    workloads = [number(g.get('workload')) for g in clean[:10]]
    recent = [v for v in workloads[:5] if v is not None]
    earlier = [v for v in workloads[5:] if v is not None]
    workload_change = None
    if len(recent)>=3 and len(earlier)>=3 and sum(earlier)>0:
        workload_change = float((sum(recent)/len(recent))/(sum(earlier)/len(earlier))-1)
        if abs(workload_change)>=.2:
            flags.append('Recent workload changed by at least 20%; historical rates may not transfer.')
    p = (baseline['wins']+.5)/(n+1) if n else None
    net = float(1+(price-1)*(1-commission))
    decisive = n/baseline['games'] if baseline['games'] else 0
    ev = decisive*(p*net-1) if p is not None else None
    lower_ev = decisive*(baseline['historical_interval'][0]*net-1) if n else None
    fresh = bool(clean and as_of-instant(clean[0]['date'])<=30*86400)
    signal = bool(n>=20 and lower_ev is not None and lower_ev>0 and fresh and not signal_context_changed and
                  (workload_change is None or abs(workload_change)<.2))
    # Never convert an exploratory signal into the production fair-probability / EV feed.
    return {'version':VERSION, 'windows':windows, 'baseline':baseline, 'matchup':matchup,'opponent':opponent,
            'venue':venue, 'games':clean[:10], 'history_games':clean, 'workload_change':workload_change,
            'model_probability':p, 'model_ev':ev, 'historical_sensitivity_ev':lower_ev,
            'break_even_probability':1/net, 'research_signal':signal,
            'calibration_status':'not_empirically_calibrated', 'flags':flags,
            'historical_replay':walk_forward(clean,line,side),
            'as_of':datetime.fromtimestamp(as_of,timezone.utc).isoformat()}


def walk_forward(games, line, side, minimum=20):
    """Expanding chronological holdout diagnostics; no in-sample fitted accuracy.

    Fixed line only. Real market-edge evaluation additionally needs archived
    point-in-time odds, injuries, selections and costs. This cannot certify EV.
    """
    line = number(line)
    if line is None or side not in ('Over','Under'):
        raise ValueError('Valid line and side required.')
    rows = sorted(games,key=lambda g:g['date'])
    history, seen, scores = [], set(), []
    for game in rows:
        value = number(game.get('value'))
        if game.get('id') in seen or not game.get('completed') or game.get('dnp') or value is None or value==line:
            continue
        seen.add(game.get('id'))
        won = int(value>line if side=='Over' else value<line)
        if len(history)>=minimum:
            probability = (sum(history)+.5)/(len(history)+1)
            scores.append(((probability-won)**2,-(won*math.log(probability)+(1-won)*math.log(1-probability))))
        history.append(won)
    return {'held_out_games':len(scores), 'brier':sum(s[0] for s in scores)/len(scores) if scores else None,
            'log_loss':sum(s[1] for s in scores)/len(scores) if scores else None,
            'edge_validated':False}

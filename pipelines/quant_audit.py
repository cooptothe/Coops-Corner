"""Offline catalog coverage and historical-data readiness audit. No HTTP or paid calls."""
import argparse
from collections import Counter
import json
from pathlib import Path
from corner.prop_markets import FAMILIES
from corner.prop_projection import plan
from pipelines.trends_service import stat_specs,LEAGUES


def report(player_logs=None):
    sports={'basketball':'basketball_nba','football':'americanfootball_nfl','baseball':'baseball_mlb','hockey':'icehockey_nhl','soccer':'soccer_epl'}
    rows=[{'sport':sports[group],'market':meta.key,'sides':list(meta.sides),**plan(sports[group],meta.key),
           'game_log_mapping':bool(sports[group] in LEAGUES and stat_specs(sports[group],meta.key))}
          for group,markets in FAMILIES.items() for meta in markets]
    result={'market_entries':len(rows),'explicit_projection_plan':len(rows),'current_game_log_mappings':sum(r['game_log_mapping'] for r in rows),
            'markets':rows,'provider_calls':0,'prediction_accuracy_established':False,'profitability_established':False,
            'main_feed':'Weighted proportional no-vig baseline; reputation priors, not fitted accuracy.',
            'props_feed':'Paired power/proportional sensitivity; unpaired margin transfer or explicit policy assumptions.',
            'one_sided_identification':'One offered price does not identify fair probability without additional data/assumptions.'}
    if player_logs:
        data=json.loads(Path(player_logs).read_text(encoding='utf-8'))['rows']
        counts=Counter(r.get('player_id') for r in data)
        result['historical_data_readiness']={'rows':len(data),'players':len(counts),'maximum_games_per_player':max(counts.values(),default=0),
            'players_with_8_games':sum(n>=8 for n in counts.values()),'independently_verified_full_dataset':False,
            'note':'Availability audit only; zero-filled, inactive, stale or unverified records must not be treated as training truth.'}
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    parser.add_argument('--player-logs')
    args=parser.parse_args()
    target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report(args.player_logs),indent=2)+'\n',encoding='utf-8')
    print('Offline quant audit saved. No provider calls; no calibrated edge claimed.')

if __name__=='__main__':main()

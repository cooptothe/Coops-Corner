"""Bounded free-data warming. Does not enable or call the paid odds collector."""
import argparse
import json
from pipelines.trends_service import Trends, contracts, ResearchUnavailable


def warm(service, items, limit=20):
    done,unavailable,seen = 0,0,set()
    for item in sorted(items,key=lambda c:c['starts_at']):
        key = item['sport_key'],item['player']
        if key in seen:continue
        seen.add(key)
        if len(seen)>limit:break
        try:
            service.research(item)
            done += 1
        except (ResearchUnavailable,ValueError):
            unavailable += 1
    return {'players_checked':done+unavailable,'available':done,'unavailable':unavailable,'odds_provider_calls':0}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit',type=int,default=20,choices=range(1,41),metavar='1-40')
    args=parser.parse_args()
    print(json.dumps(warm(Trends(),contracts(research=True,persist=True).values(),args.limit)))


if __name__=='__main__':main()

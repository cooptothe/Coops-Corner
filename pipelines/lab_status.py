"""Saved Lab inventory diagnostic. No ESPN or Odds API requests."""
import json
import os
from collections import Counter
from pathlib import Path
from dotenv import dotenv_values

def main():
    config=Path('/srv/corner/config/staging.env')
    if config.exists():
        for key,value in dotenv_values(config).items():
            if value is not None:os.environ.setdefault(key,value)
    from pipelines.trends_service import contracts
    items=contracts(research=True,persist=True)
    players={(c['sport_key'],c['player']) for c in items.values()}
    print(json.dumps({'lab_quotes':len(items),'players':len(players),
        'sports':dict(Counter(c['sport_key'] for c in items.values())),
        'provider_calls':0,'result':'ready' if items else 'no_saved_prop_inventory'}))

if __name__=='__main__':main()

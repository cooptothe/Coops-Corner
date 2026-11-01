"""Offline November schedule simulation; prints estimates, no writes or network calls."""
import sys,json,math
from pathlib import Path
from datetime import datetime,timezone,timedelta
from collections import Counter,defaultdict
from corner.collection_policy import FAMILIES,interval,parse,CENTRAL,open_now
root=Path(__file__).resolve().parents[1]/'corner/forecasts'
from corner.collection_policy import COUNTDOWN_BANDS
bands=COUNTDOWN_BANDS
families={'nfl':'football','nba':'basketball','wnba':'basketball','nhl':'hockey','mlb':'baseball','mls':'soccer','epl':'soccer','laliga':'soccer','bundesliga':'soccer','seriea':'soccer','ligue1':'soccer','ucl':'soccer'}
prior={'main':[(3600,120),(7200,180),(21600,300),(43200,600),(86400,900)],'props':[(7200,60),(14400,120),(21600,180),(43200,300),(86400,600)]}
def previous(kind,seconds):return next((v for upper,v in prior[kind] if seconds<=upper),prior[kind][-1][1])
def proposed(kind,seconds):return next((v for upper,v in bands[kind] if seconds<=upper),bands[kind][-1][1])
events=json.loads((root/'november-2026-events.json').read_text(encoding='utf-8'))
begin=parse('2026-11-01T00:00:00Z');stop=parse('2026-12-01T00:00:00Z');cut=parse('2026-11-21T06:00:00Z')
costs={};counts=Counter();uncertain=Counter()
for e in events:
    start=parse(e['start_utc'])
    if begin<=start<cut:counts[e['league']]+=1
    if not e['time_confirmed']:uncertain[e['league']]+=1
for version in ('existing','proposed'):
    result=Counter();by_league=Counter();early=Counter()
    for e in events:
        fam=families.get(e['league'])
        if fam not in FAMILIES:continue
        start=parse(e['start_utc']);t=math.ceil(max(begin.timestamp(),start.timestamp()-86400)/30)*30;last=None
        while t<min(start.timestamp(),stop.timestamp()):
            now=datetime.fromtimestamp(t,timezone.utc)
            if open_now(now):
                due=previous('props',start.timestamp()-t) if version=='existing' else proposed('props',start.timestamp()-t)
                if last is None or t-last>=due:
                    last=t;c=len(FAMILIES[fam])*2;result['props']+=c;by_league[e['league']]+=c
                    if now<cut:early['props']+=c
            t+=30
    # Main odds are one request per league/group, not one per game.
    starts=defaultdict(list)
    for e in events:starts[e['league']].append(parse(e['start_utc']).timestamp())
    # Assume every covered non-tennis league stays active all month, even idle days.
    for league in [*families,'ncaaf','ncaab','wncaab','mma']:
        last=None;t=begin.timestamp()
        ordered=sorted(starts.get(league,[]));i=0
        while t<stop.timestamp():
            now=datetime.fromtimestamp(t,timezone.utc)
            while i<len(ordered) and ordered[i]<=t:i+=1
            near=ordered[i] if i<len(ordered) and ordered[i]<=t+86400 else None
            if open_now(now):
                due=(previous('main',near-t) if near else 120) if version=='existing' else (proposed('main',near-t) if near else 900)
                if last is None or t-last>=due:
                    last=t;result['main']+=6
                    if now<cut:early['main']+=6
            t+=30
    costs[version]=dict(full_month=dict(result),through_nov20=dict(early),props_by_league=dict(by_league))
output=dict(counts_through_nov20=dict(counts),unconfirmed_start_times=dict(uncertain),costs=costs,bands=bands,events=events)

print(json.dumps({k:v for k,v in output.items() if k!='events'},indent=2))

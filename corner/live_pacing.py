"""Pure live pacing: provider update floors, conservative slate demand, fixed caps."""
import math
from datetime import timedelta
from corner.collection_policy import CENTRAL, aware, parse

VERSION = 'provider-paced-live-v1'
FLOORS = {'standard':40,'exchange':10}


def plan(now, cycle_end, inventory, *, spent_month, spent_today, monthly_cap, daily_cap, available_main):
    now=aware(now);cycle_end=aware(cycle_end)
    local=now.astimezone(CENTRAL)
    close=CENTRAL.localize(local.replace(tzinfo=None,hour=22,minute=0,second=0,microsecond=0)).astimezone(now.tzinfo)
    close=min(close,cycle_end)
    days=max(1,math.ceil((cycle_end-now).total_seconds()/86400))
    monthly_remaining=max(0,monthly_cap-spent_month)
    day_target=min(daily_cap,max(0,(monthly_remaining+spent_today)//days))
    available=max(0,min(monthly_remaining,daily_cap-spent_today,day_target-spent_today,available_main))
    # Durations are conservative planning assumptions, never game-status claims.
    # They neither exclude a collection scope nor declare a game finished.
    windows={}
    for event in [*inventory.get('events',[]),*inventory.get('live_events',[])]:
        sport=event.get('sport_key','')
        try:start=parse(event['commence_time'])
        except (KeyError,ValueError,TypeError,AttributeError):continue
        hours=8 if sport.startswith('mma_') else 5 if sport.startswith('tennis_') else 4.5 if sport.startswith(('americanfootball_','baseball_')) else 3.5
        end=start+timedelta(hours=hours)
        if start<=now and end<=now and start>=now-timedelta(hours=12):
            end=now+timedelta(minutes=30) # allow for extended/uncertain live games
        first=max(now,start);last=min(close,end)
        if last>first:windows.setdefault(sport,[]).append((first.timestamp(),last.timestamp()))
    league_seconds=0
    for spans in windows.values():
        merged=[]
        for first,last in sorted(spans):
            if merged and first<=merged[-1][1]:merged[-1]=(merged[-1][0],max(last,merged[-1][1]))
            else:merged.append((first,last))
        league_seconds+=sum(last-first for first,last in merged)
    # Three requested main markets per group. Cost is reserved at the ceiling;
    # actual lower provider charges automatically leave more room at next plan.
    demand=league_seconds*3*sum(1/value for value in FLOORS.values())
    # Maximize the slower group's freshness first. Standard target books must
    # not be starved merely to refresh exchange references at ten seconds.
    units=league_seconds*3
    if not available:intervals={group:86400 for group in FLOORS}
    elif 2*units/available>=40:
        shared=max(40,math.ceil(2*units/available))
        intervals={'standard':shared,'exchange':shared}
    else:
        exchange_budget=available-units/40
        intervals={'standard':40,'exchange':max(10,math.ceil(units/exchange_budget))}
    return {'version':VERSION,'checked_at':now.timestamp(),'provider_floor_seconds':FLOORS,
        'interval_seconds':intervals,'remaining_today_paced':available,
        'remaining_month':monthly_remaining,'day_target':day_target,
        'forecast_league_hours_remaining':round(league_seconds/3600,2),
        'forecast_credits_at_provider_floors':math.ceil(demand),
        'monthly_cap':monthly_cap,'daily_cap':daily_cap,
        'forecast_basis':'Current provider event inventory, conservative duration windows; hard ledger caps remain authoritative.'}

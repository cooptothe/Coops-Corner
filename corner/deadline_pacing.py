"""Pure owner-directed deadline pacing, using charge observations and source floors."""
import math
from datetime import datetime,timedelta,timezone
from corner.collection_policy import CENTRAL,aware,parse,interval,provider_floor

START=parse('2026-11-04T00:00:00Z')
END=parse('2026-11-21T06:00:00Z')  # Nov 20 ends at midnight Central.
VERSION='nov20-deadline-v1'

def active(now):return START<=aware(now)<END

def remaining_seconds(now,cycle_end,day_weights=None):
    now=aware(now);end=min(aware(cycle_end),END)
    day=now.astimezone(CENTRAL).date();seconds=0
    current_weight=(day_weights or {}).get(day.isoformat(),1)
    while day<=end.astimezone(CENTRAL).date():
        first=CENTRAL.localize(datetime.combine(day,datetime.min.time()).replace(hour=6)).astimezone(timezone.utc)
        last=CENTRAL.localize(datetime.combine(day+timedelta(days=1),datetime.min.time())).astimezone(timezone.utc)
        seconds+=max(0,(min(last,end)-max(first,now)).total_seconds())*((day_weights or {}).get(day.isoformat(),current_weight)/current_weight)
        day+=timedelta(days=1)
    # Overnight demand uses today's rate, then reduces the following day's rate.
    return max(1,seconds) if now<end else 0

def forecast_day_weights():
    # Frozen public schedule: normalize partial Nov 4 to credits/hour so it is
    # comparable with later full 18-hour days. No network calls in the worker.
    from pathlib import Path
    import json
    path=Path(__file__).resolve().parent/'forecasts/november4-2026-deadline.json'
    try:
        source=json.loads(path.read_text())
        first=parse(source['as_of_utc']).astimezone(CENTRAL)
        weights={day:sum(cost.values())/(24-max(6,first.hour+first.minute/60) if day==first.date().isoformat() else 18)
                 for day,cost in source['daily_maximum_demand'].items()}
        positive=sorted(v for v in weights.values() if v>0)
        fallback=positive[len(positive)//2] if positive else 1
        return {day:(value if value>0 else fallback) for day,value in weights.items()}
    except (OSError,ValueError,KeyError,ZeroDivisionError):return {}

def plan(now,cycle_end,jobs,remaining,samples=None,day_weights=None):
    samples=samples or {};seconds=remaining_seconds(now,cycle_end)
    budget_seconds=remaining_seconds(now,cycle_end,day_weights)
    target=max(0,remaining)/budget_seconds if budget_seconds else 0
    specs=[]
    for job in jobs:
        sample=samples.get(job.key)
        # A verified zero-cost response can run at the source floor; a changed
        # response remains bounded by a full-cost reservation before dispatch.
        cost=(sample['actual']/sample['reserved']*job.cost) if sample and sample['reserved'] else job.cost
        base=interval(job.kind,job.group,now,parse(job.starts_at) if job.starts_at else None)
        minimum=base if job.kind=='additional' else provider_floor(job.kind,job.group)
        specs.append((job,cost,base,minimum))
    demand=lambda scale:sum(cost/max(floor,base*scale) for _,cost,base,floor in specs)
    floor_rate=demand(0)
    lo,hi=0.,1.
    while demand(hi)>target and hi<1e9:hi*=2
    if target and floor_rate>target:
        for _ in range(60):
            mid=(lo+hi)/2
            if demand(mid)>target:lo=mid
            else:hi=mid
        scale=hi
    else:scale=0.
    periods={job.key:max(floor,math.ceil(base*scale)) if target else 86400 for job,_,base,floor in specs}
    rates={'main':0.,'props':0.}
    for job,cost,_,_ in specs:
        if target:rates[job.pool]+=cost/periods[job.key]
    return dict(version=VERSION,checked_at=aware(now).timestamp(),deadline_utc=END.isoformat(),
        remaining=remaining,remaining_regular_hours=round(seconds/3600,3),
        unweighted_target_credits_per_hour=round(max(0,remaining)/seconds*3600,2) if seconds else 0,
        schedule_weighted=bool(day_weights),target_credits_per_hour=round(target*3600,2),
        expected_credits_per_hour=round(sum(rates.values())*3600,2),floor_capacity_credits_per_hour=round(floor_rate*3600,2),
        state='deadline_closed' if not seconds else 'source_capacity_limited' if floor_rate<target else 'paced',
        interval_seconds=periods,pool_rates=rates)

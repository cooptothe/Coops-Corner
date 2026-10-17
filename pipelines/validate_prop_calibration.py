"""Offline scoring of a frozen, independently settled binary-prop evaluation set.

This evaluates forecasts; it does not fit or silently deploy calibration weights.
Usage: python -m pipelines.validate_prop_calibration --input holdout.jsonl
"""
import argparse
from datetime import datetime
from decimal import Decimal as D, localcontext
import json
from pathlib import Path


def score(records):
    seen = set()
    brier, loss = D(0), D(0)
    bins = [[0, D(0), 0] for _ in range(10)]
    events = set()
    with localcontext() as ctx:
        ctx.prec = 50
        for row in records:
            identity = (row['event_id'], row['market'], row['player'], row['line'])
            if identity in seen:
                raise ValueError('one frozen forecast per player/market/line; duplicate or opposite side found')
            seen.add(identity)
            events.add(row['event_id'])
            times = [datetime.fromisoformat(row[k].replace('Z', '+00:00'))
                     for k in ('predicted_at', 'starts_at', 'resolved_at')]
            if any(t.utcoffset() is None for t in times) or not times[0] < times[1] <= times[2]:
                raise ValueError('aware pregame prediction and later settlement required')
            if row.get('settlement') != 'decisive' or row.get('synthetic') is not False:
                raise ValueError('real independently verified decisive outcomes only; separate pushes/voids')
            if not row.get('outcome_source') or not row.get('model_version'):
                raise ValueError('outcome provenance and frozen model version required')
            y = row['won']
            p = D(str(row['probability']))
            if type(y) is not int or y not in (0, 1) or not p.is_finite() or not 0 < p < 1:
                raise ValueError('binary outcome and open-interval probability required')
            brier += (p-y)**2
            loss -= p.ln() if y else (1-p).ln()
            bucket = bins[min(9, int(p*10))]
            bucket[0] += 1
            bucket[1] += p
            bucket[2] += y
        if not seen:
            raise ValueError('no historical outcomes supplied; cannot claim calibration')
        return dict(count=len(seen), distinct_events=len(events), brier=str(brier/len(seen)),
                    log_loss=str(loss/len(seen)), calibration_claim='not_established_by_scoring_alone',
                    reliability=[dict(bin=i, count=n, mean_forecast=str(p/n), observed_rate=str(D(y)/n))
                                 for i, (n, p, y) in enumerate(bins) if n])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    args = parser.parse_args()
    records = [json.loads(line) for line in args.input.read_text(encoding='utf-8').splitlines() if line.strip()]
    print(json.dumps(score(records), sort_keys=True))


if __name__ == '__main__':
    main()

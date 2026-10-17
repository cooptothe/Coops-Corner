"""Point-in-time forecast diagnostics. Scores never authorize betting by themselves."""
from collections import defaultdict
import math


def evaluate(records):
    games=defaultdict(list);seen=set()
    for row in records:
        ident=(row['model_id'],row['event_id'],row['selection_id'])
        if ident in seen:raise ValueError('Duplicate scored prediction')
        seen.add(ident)
        times=[row[k] for k in ('features_as_of','predicted_at','event_start','settled_at','train_cutoff')]
        if any(type(x) not in (int,float) or not math.isfinite(x) for x in times):raise ValueError('Finite point-in-time timestamps required')
        if not row['train_cutoff']<row['predicted_at']<=row['event_start']<row['settled_at'] or row['features_as_of']>row['predicted_at']:
            raise ValueError('Future information or training leakage')
        p=row['probability'];outcome=row['outcome']
        if type(p) not in (int,float) or not math.isfinite(p) or not 0<p<1 or type(outcome) is not int or outcome not in (0,1):
            raise ValueError('Interior probability and exact decisive outcome required')
        games[(row['model_id'],row['event_id'])].append(((p-outcome)**2,-(outcome*math.log(p)+(1-outcome)*math.log1p(-p))))
    models=defaultdict(list)
    for (model,event),values in games.items():
        models[model].append((sum(v[0] for v in values)/len(values),sum(v[1] for v in values)/len(values),len(values)))
    return {model:{'event_balanced_brier':sum(v[0] for v in values)/len(values),
                   'event_balanced_log_loss':sum(v[1] for v in values)/len(values),
                   'events':len(values),'predictions':sum(v[2] for v in values),
                   'edge_validated':False,'profitability_verified':False}
            for model,values in models.items()}

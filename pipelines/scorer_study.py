"""Deterministic offline stress study. Synthetic results are not a backtest."""
import argparse
import json
import math
import random
from pathlib import Path
from corner.scorer_research import poisson_anytime,negative_binomial_anytime


def run(seed=20261017, count=50000):
    rng=random.Random(seed)
    methods={name:dict(squared_error=0,absolute_error=0,false_positive_edges=0,flagged=0) for name in ('raw_implied','proportional','equal_vig','allocation_lower')}
    scenarios=0; violations=0; excluded=0
    for _ in range(count):
        p=rng.uniform(.02,.80); h=rng.uniform(.01,.25); share=rng.random()
        q=p+share*h;other=1-p+(1-share)*h
        if q>=1 or other>=1:excluded+=1;continue
        scenarios+=1
        target=(1+rng.uniform(-.15,.15))/p
        estimates={'raw_implied':q,'proportional':q/(1+h),'equal_vig':max(0,q-h/2),'allocation_lower':max(0,q-h)}
        violations+=not (max(0,q-h)-1e-12<=p<=q+1e-12)
        for name,estimate in estimates.items():
            row=methods[name];row['squared_error']+=(estimate-p)**2;row['absolute_error']+=abs(estimate-p)
            flag=estimate*target>1;row['flagged']+=flag
            row['false_positive_edges']+=bool(flag and p*target<=1)
    for row in methods.values():
        row['rmse']=math.sqrt(row.pop('squared_error')/scenarios)
        row['mean_absolute_error']=row.pop('absolute_error')/scenarios
        row['false_positive_share_of_flagged']=row['false_positive_edges']/row['flagged'] if row['flagged'] else None
    return {'study':'synthetic asymmetric-vig stress test','seed':seed,'attempted':count,'valid_scenarios':scenarios,'excluded_invalid_quote_pairs':excluded,
            'known_overround_supplied':True,'allocation_bound_violations':violations,'methods':methods,
            'count_model_sensitivity':[{'mean_count':rate,'poisson':poisson_anytime(rate),'gamma_poisson_k1':negative_binomial_anytime(rate,1)} for rate in (.2,.5,1,2)],
            'limitations':['Synthetic ground truth; not real ATD/ATG performance.','Overround ceiling is known in this experiment; real Yes-only prices do not supply it.','Bounds depend on nonnegative per-side vig; shading can violate that assumption.','No fitted book ranking, liquidity model or calibrated player scoring rate.']}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    result=run();args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'output':str(args.output),'valid_scenarios':result['valid_scenarios'],'provider_calls':0,'synthetic':True}))


if __name__=='__main__':main()

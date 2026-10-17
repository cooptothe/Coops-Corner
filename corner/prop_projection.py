"""Versioned distribution baselines, not calibrated betting recommendations.

Uses only pre-as-of completed observations of the exact statistic/period. A
projection is never promoted into the market EV feed by this module.
"""
from functools import lru_cache
import math
from statistics import mean, median, variance
from corner.prop_trends import instant, number

VERSION='projection-research/2026-10-17.1'


def plan(sport,market):
    from corner.prop_markets import market_meta
    meta=market_meta(sport,market)
    if meta is None:return {'method':'unavailable','requires':['documented_market_and_settlement']}
    if market.endswith(('_first','_last')) or market in ('player_1st_td','player_last_td'):
        return {'method':'competing_scoring_hazards','requires':['complete_field_including_opposition','time_varying_scoring_opportunities','participation_and_no_scorer_rules']}
    if market.endswith('_q1'):return {'method':'count_distribution','requires':['first_quarter_only_game_logs','expected_first_quarter_minutes']}
    if market in ('player_anytime_td','player_goal_scorer_anytime'):
        return {'method':'count_anytime','requires':['complete_eligible_scoring_counts','participation_and_settlement_rules']}
    if meta.sides==('Yes','No'):
        return {'method':'binary_event','requires':['exact_binary_event_results','participation_and_settlement_rules']}
    if 'longest' in market or market.endswith('_long'):
        return {'method':'empirical_game_maximum','requires':['same_period_maximum_results','opportunities_and_no_attempt_rules']}
    if market.endswith('_yds'):
        return {'method':'discretized_student_t','requires':['same_period_yardage','expected_opportunities']}
    return {'method':'count_distribution','requires':['same_period_statistic','expected_workload']}


def _logadd(a,b):
    top=max(a,b)
    return top+math.log1p(math.exp(min(a,b)-top))


def nb_cdf(k,shape,mu):
    """Negative-binomial count CDF, evaluated in log space without tail underflow."""
    if k<0:return 0.0
    if not math.isfinite(shape) or not math.isfinite(mu) or shape<=0 or mu<0:raise ValueError('Invalid count parameters')
    if mu==0:return 1.0
    if k>10000:raise ValueError('Count threshold outside numerical research bounds')
    logp=-math.log1p(mu/shape)
    logq=math.log(mu)-math.log(shape+mu)
    term=shape*logp;total=term
    for j in range(1,math.floor(k)+1):
        term+=math.log(shape+j-1)-math.log(j)+logq
        total=_logadd(total,term)
    return min(1.0,max(0.0,math.exp(total)))


def _beta_fraction(a,b,x):
    # Lentz evaluation of the standard incomplete-beta continued fraction.
    tiny=1e-300;total=a+b;c=1.0;d=1-total*x/(a+1)
    if abs(d)<tiny:d=tiny
    d=1/d;h=d
    for m in range(1,401):
        two=2*m
        for numerator in (m*(b-m)*x/((a+two-1)*(a+two)), -(a+m)*(total+m)*x/((a+two)*(a+two+1))):
            d=1+numerator*d;c=1+numerator/c
            if abs(d)<tiny:d=tiny
            if abs(c)<tiny:c=tiny
            d=1/d;delta=d*c;h*=delta
        if abs(delta-1)<1e-13:return h
    raise ValueError('Predictive CDF failed to converge')


def beta_cdf(x,a,b):
    if x<=0:return 0.0
    if x>=1:return 1.0
    factor=math.exp(math.lgamma(a+b)-math.lgamma(a)-math.lgamma(b)+a*math.log(x)+b*math.log1p(-x))
    if x<(a+1)/(a+b+2):return factor*_beta_fraction(a,b,x)/a
    return 1-factor*_beta_fraction(b,a,1-x)/b


def student_cdf(x,df):
    if x==0:return .5
    tail=.5*beta_cdf(df/(df+x*x),df/2,.5)
    return tail if x<0 else 1-tail


def _branches(cdf,line,side):
    k=math.floor(line)
    below=cdf(k-1) if line==k else cdf(k)
    push=max(0,cdf(k)-below) if line==k else 0.0
    over=max(0,1-below-push)
    return (over,push,below) if side=='Over' else (below,push,over)


def _empirical(values,line,side):
    wins=sum(v>line if side=='Over' else v<line for v in values)
    pushes=sum(v==line for v in values)
    losses=len(values)-wins-pushes
    # Half-line integer statistics cannot push. Exact lines keep a refund branch.
    possible_push=any(not float(v).is_integer() for v in values) or float(line).is_integer()
    denominator=len(values)+(1.5 if possible_push else 1)
    return ((wins+.5)/denominator,(pushes+.5)/denominator if possible_push else 0.0,(losses+.5)/denominator)


def forecast(games,*,sport,market,line,side,price,commission,as_of):
    method=plan(sport,market)
    result={'version':VERSION,'method':method['method'],'edge_validated':False,
            'calibration_status':'not_empirically_calibrated','live_feed_eligible':False,
            'required_context':method['requires']}
    if method['method'] in ('unavailable','competing_scoring_hazards'):
        return {**result,'status':'needs_context','reason':'The required market or full-field event-order inputs are missing.'}
    if market.endswith('_q1') and any(g.get('period')!='first_quarter' for g in games):
        return {**result,'status':'needs_context','reason':'Full-game logs cannot price a first-quarter contract.'}
    d,c=number(price),number(commission)
    if d is None or d<=1 or c is None or not 0<=c<=1:return {**result,'status':'unavailable','reason':'Exact target price and known fees required.'}
    if side in ('Yes','No'):
        if method['method'] not in ('count_anytime','binary_event'):return {**result,'status':'needs_context','reason':'Exact binary settlement mapping required.'}
        threshold=.5;choice='Over' if side=='Yes' else 'Under'
    else:
        point=number(line)
        if point is None or side not in ('Over','Under'):return {**result,'status':'unavailable','reason':'Exact selection and line required.'}
        threshold=float(point);choice=side
    unique={};conflicts=set()
    for g in games:
        at=instant(g.get('date'));v=number(g.get('value'));ident=g.get('id')
        if not ident or not g.get('completed') or g.get('dnp') or at is None or not 0<as_of-at<=366*86400 or v is None:continue
        pair=(at,float(v))
        if ident in unique and unique[ident]!=pair:conflicts.add(ident)
        unique[ident]=pair
    observations=sorted((v for key,v in unique.items() if key not in conflicts),reverse=True)[:40]
    values=[v for _,v in observations];n=len(values)
    if n<8:return {**result,'status':'needs_data','games':n,'reason':'At least eight independent completed games are required for this research baseline.'}
    if method['method']=='binary_event' and any(v not in (0,1) for v in values):return {**result,'status':'needs_context','reason':'Exact binary game outcomes required.'}
    empirical=_empirical(values,threshold,choice)
    candidates=[('smoothed_empirical',empirical)]
    projected_mean=mean(values);predictive_range=None
    if method['method'] in ('count_distribution','count_anytime') and all(v>=0 and v.is_integer() for v in values):
        shape=sum(values)+.5;mu=shape/n
        candidates.append(('gamma_poisson_predictive',_branches(lambda k:nb_cdf(k,shape,mu),threshold,choice)))
        projected_mean=mu
        samplevar=variance(values)
        if samplevar>projected_mean and projected_mean>0:
            dispersion=projected_mean**2/(samplevar-projected_mean)
            candidates.append(('overdispersed_negative_binomial',_branches(lambda k:nb_cdf(k,dispersion,projected_mean),threshold,choice)))
        def quantile(q):
            low,high=0,max(1,math.ceil(mu*2+10))
            while nb_cdf(high,shape,mu)<q:
                high*=2
                if high>10000:raise ValueError('Predictive count range too broad')
            while low<high:
                mid=(low+high)//2
                if nb_cdf(mid,shape,mu)>=q:high=mid
                else:low=mid+1
            return low
        predictive_range=[quantile(.1),quantile(.9)]
    elif method['method']=='discretized_student_t' and all(v.is_integer() for v in values) and variance(values)>0:
        scale=math.sqrt(variance(values)*(1+1/n))
        cdf=lambda k:student_cdf((k+.5-projected_mean)/scale,n-1)
        candidates.append(('normal_unknown_mean_variance_predictive',_branches(cdf,threshold,choice)))
    # Disagreement is sensitivity to assumptions, not a confidence interval.
    central=candidates[1][1] if len(candidates)>1 else empirical
    net=1+(float(d)-1)*(1-float(c))
    estimates=[{'method':name,'win':w,'push':p,'loss':l,'ev':w*(net-1)-l} for name,(w,p,l) in candidates]
    return {**result,'status':'research_only','games':n,'projected_mean':projected_mean,'historical_median':median(values),
            'predictive_10_90':predictive_range,'probability':central[0],'push_probability':central[1],
            'loss_probability':central[2],'model_ev':central[0]*(net-1)-central[2],
            'sensitivity_ev':[min(e['ev'] for e in estimates),max(e['ev'] for e in estimates)],
            'models':estimates,'assumptions':['Same statistic, period, settlement and participation rules.',
                'Unchanged role/opportunity distribution; no fitted injury or matchup effect.',
                'Model range is assumption sensitivity, not calibrated confidence.',
                'No verified out-of-sample edge; no stake recommendation.']}


def competing_scorer(rates,player,*,complete_field=False):
    if not complete_field or player not in rates or not rates:raise ValueError('Complete participating scorer field including opposition required')
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 for v in rates.values()):raise ValueError('Finite nonnegative exposure-adjusted rates required')
    total=sum(rates.values());selected=rates[player]
    first=selected/total*(-math.expm1(-total)) if total else 0.0
    return {'anytime':-math.expm1(-selected),'first':first,'last':first,'no_scorer':math.exp(-total),
            'assumption':'Independent constant scoring hazards over the exact eligible period.',
            'edge_validated':False,'live_feed_eligible':False}

"""Explain every retained prop quote, including markets without a priceable edge."""
from collections import Counter
from corner.book_policy import supported_book
from corner.prop_markets import FAMILIES, market_meta
from corner.prop_projection import plan
from corner.pricing import fee_policy


def coverage(events,priced):
    identifiers={row['id'] for row in priced};counts=Counter();markets={}
    for eid,event in events.items():
        for key,stored in event.get('markets',{}).items():
            meta=market_meta(event['sport_key'],key)
            item=markets.setdefault((event['sport_key'],key),{'sport_key':event['sport_key'],'market':key,
                'label':meta.label if meta else key,'projection':plan(event['sport_key'],key),'quotes':0,'priced':0})
            for quote in stored.get('quotes',[]):
                if not supported_book(quote.get('book','')):continue
                item['quotes']+=1
                ident=f'{eid}:{key}:{quote.get("player","")}:{quote.get("point") or ""}:{quote.get("book","")}:{quote.get("side","")}'
                if ident in identifiers:reason='market_priced';item['priced']+=1
                elif meta is None:reason='undocumented_market'
                elif fee_policy(quote.get('book','')).commission is None:reason='execution_fee_or_payoff_missing'
                else:reason='projection_or_reference_context_needed'
                counts[reason]+=1
    return {'retained_quotes':sum(counts.values()),'outcomes':dict(counts),'markets':list(markets.values()),
            'catalog_market_count':sum(len(v) for v in FAMILIES.values()),'provider_calls':0,
            'scope':'Retained quotes only. Missing provider markets are not fabricated.',
            'projection_edges_validated':False,
            'positive_estimates':sum(float(row['ev'])>0 for row in priced),
            'dfs_assumption_estimates':sum(bool(row.get('dfs_reference_books')) for row in priced),
            'reference_requirement':'Two other distinct cash-book reference sources; target excluded. DFS is not eligible.'}

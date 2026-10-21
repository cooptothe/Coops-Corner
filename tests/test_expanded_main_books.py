import unittest
from decimal import Decimal
from dataclasses import asdict
from pathlib import Path
import json
import tempfile

from corner.collection_policy import STANDARD, BASE_STANDARD, PROP_STANDARD, EXCHANGE, Job, POOLS, interval
from corner.pricing import fee_policy
from corner.links import clean_url
from pipelines.odds_ingestion import PARAMS
from pipelines.props_ingestion import BOOKS
from pipelines.collection_publication import MainPublisher
from api.database import build_raw, DEFAULT_REFERENCES
from api.catalog import FixtureCatalog
from tests.test_database_catalog import board, q, PEOPLE, NOW


class ExpandedMainTests(unittest.TestCase):
    def test_book_tiers_and_props_scope_are_preserved(self):
        self.assertEqual(len(STANDARD),9)
        self.assertEqual(len(PROP_STANDARD),10)
        self.assertEqual(len(set(PARAMS['bookmakers'].split(','))),15)
        self.assertEqual(len(set(BOOKS.split(','))),16)
        for book in ('betonlineag','williamhill_us','bovada'):
            self.assertIn(book,STANDARD)
            self.assertIn(book,PARAMS['bookmakers'].split(','))
            self.assertEqual(fee_policy(book).commission,Decimal(0))
        self.assertIn('betonlineag',PROP_STANDARD)
        self.assertIn('bovada',PROP_STANDARD)
        self.assertIn('betonlineag',BOOKS.split(','))
        self.assertIn('bovada',BOOKS.split(','))
        self.assertIn('fanatics',PROP_STANDARD)
        self.assertIn('williamhill_us',PROP_STANDARD)
        self.assertIn('williamhill_us',BOOKS.split(','))
        job=Job('main','basketball_nba','standard',STANDARD,('h2h','spreads','totals'))
        job.validate();self.assertEqual(job.cost,3)
        # Even 82 keys polling all sixteen hours on a 31-day month fit main pool,
        # including 50 additional events per day (30 calls, five market keys).
        self.assertLessEqual(82*960*3*31 + 50*30*5*31,POOLS['main'])
        self.assertEqual(interval('main','standard',NOW),60)

    def test_new_cash_books_are_targets_and_selected_main_references(self):
        for book in ('betonlineag','williamhill_us','bovada'):
            self.assertIn(book,DEFAULT_REFERENCES)
            raw=build_raw(board()+[q(book,'moneyline',s,'4') for s in ('home','away')],PEOPLE,now=NOW)
            self.assertIn(book,raw['target_books'])
            catalog=FixtureCatalog(raw=raw)
            self.assertTrue(any(row.kind=='positive_ev' and catalog.quote_map[row.calculation.target_quote_id].sportsbook_id==book for row in catalog.rows))

    def test_main_reference_pairs_are_used_but_never_for_their_own_target(self):
        from corner.prop_markets import PROP_SHARP_BOOKS
        rows=board()+[q(b,'moneyline',side,'4') for b in ('betonlineag','bovada') for side in ('home','away')]
        catalog=FixtureCatalog(raw=build_raw(rows,PEOPLE,now=NOW))
        ev=[row for row in catalog.rows if row.kind=='positive_ev']
        dk=[row for row in ev if catalog.quote_map[row.calculation.target_quote_id].sportsbook_id=='draftkings']
        self.assertTrue(dk)
        self.assertTrue({'betonlineag','bovada'} <= {b.sportsbook_id for b in dk[0].calculation.reference_books})
        for row in ev:
            target=catalog.quote_map[row.calculation.target_quote_id].sportsbook_id
            self.assertNotIn(target,{b.sportsbook_id for b in row.calculation.reference_books})
        self.assertIn('betonlineag',PROP_SHARP_BOOKS)
        self.assertIn('bovada',PROP_SHARP_BOOKS)

    def test_books_reach_arbs_middles_quotes_and_promo_calculator(self):
        from corner.featured_promos import PromoTerms, convert_promo_back_hedge
        for book in ('betonlineag','williamhill_us','bovada'):
            rows=board()+[q(book,'moneyline',side,'4') for side in ('home','away')]
            rows += [q(book,'spread','home','2.10','-2.5'),q(book,'spread','away','2.10','2.5')]
            c=FixtureCatalog(raw=build_raw(rows,PEOPLE,now=NOW))
            self.assertTrue(any(q.sportsbook_id==book for q in c.quotes))
            self.assertTrue(any(row.kind=='arbitrage' and book in row.sportsbook_ids for row in c.rows))
            self.assertTrue(any(row.kind=='middle' and book in row.sportsbook_ids for row in c.rows))
            promo=next(o for o in c.offers.values() if o.sportsbook_id==book and o.market_key=='h2h')
            hedge=next(o for o in c.offers.values() if o.sportsbook_id=='draftkings' and o.contract_id==promo.contract_id and o.selection_id!=promo.selection_id)
            terms=PromoTerms('terms:1','bonus_stake_not_returned',Decimal(100),Decimal(100),Decimal('1.5'),Decimal(0),'synthetic:eligibility',True)
            result=convert_promo_back_hedge(c.contracts[promo.contract_id],promo,hedge,terms)
            self.assertGreater(result.hedge_stake,Decimal(0))

    def test_verified_book_domains_only(self):
        for book,host in [('betonlineag','www.betonline.ag'),('bovada','www.bovada.lv'),('williamhill_us','sportsbook.caesars.com')]:
            url=f'https://{host}/sports'
            self.assertEqual(clean_url(url,book),url)
            self.assertIsNone(clean_url(f'https://{host}.evil.example/sports',book))

    def test_old_six_book_publication_replays_without_rewriting_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            legacy=Job('main','basketball_nba','standard',BASE_STANDARD,('h2h','spreads','totals'))
            with self.assertRaises(ValueError):legacy.validate()
            manifests=[]
            def ingest(path,**kwargs):manifests.append(json.loads((path/'manifest.json').read_text()))
            publisher=MainPublisher(Path(folder),lambda:None,ingest)
            record={'job':asdict(legacy),'events':[],'captured_at':NOW.isoformat()}
            publisher('a'*48,record);publisher('a'*48,record)
            self.assertEqual(manifests[0],manifests[1])
            self.assertEqual(manifests[0]['parameters']['bookmakers'],','.join(BASE_STANDARD))
            invalid={**record,'job':{**record['job'],'books':BASE_STANDARD[:-1]}}
            with self.assertRaises(ValueError):publisher('b'*48,invalid)

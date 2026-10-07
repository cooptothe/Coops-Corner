"""Featured binding and disposable PostgreSQL persistence acceptance.

DB cases create/drop only a uniquely named test database; never migrate main DB.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import threading
import unittest
from uuid import uuid4

from corner.featured_markets import normalize_featured_payload
from corner.featured_matching import (BindingError, BookRoute, MARKET_TYPES, MarketRoute,
                                     SelectionRoute, bind_snapshot)
from corner.featured_store import FeaturedConflict, ingest_featured_payload, read_featured_streams

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2030, 1, 1, 19, tzinfo=timezone.utc)
FIXTURE = ROOT / 'fixtures/odds_api/v4/featured_six_markets_demo.json'


def synthetic_routes(snapshot):
    # Fixture-only complete catalog; never a production inference algorithm.
    markets, books = {}, {}
    for quote in snapshot.quotes:
        key = quote.event_id, quote.sport_key, quote.market_key
        markets.setdefault(key, {})[(quote.selection_name, quote.point)] = None
        books.setdefault(quote.bookmaker_key, str(uuid4()))
    return (tuple(MarketRoute(*key, str(uuid4()), tuple(SelectionRoute(name, point, str(uuid4()))
                  for name, point in selections)) for key, selections in markets.items()),
            tuple(BookRoute(key, value) for key, value in books.items()))


class FeaturedBindingTests(unittest.TestCase):
    def test_quarter_lines_and_integer_push_omissions_rejected(self):
        from corner.featured_queries import _shape
        for point,refund,expected in (('2.25',True,'quarter'),('2',False,'push/refund')):
            rows = {'a':{'side':'over','point':Decimal(point),'selected_participant_id':None},
                    'b':{'side':'under','point':Decimal(point),'selected_participant_id':None}}
            with self.subTest(point=point), self.assertRaisesRegex(BindingError,expected):
                _shape('totals',rows,('a','b'),refund)

    def test_totals_with_different_thresholds_cannot_make_back_cover(self):
        from corner.featured_queries import _shape
        rows = {'a':{'side':'over','point':Decimal('2.5'),'selected_participant_id':None},
                'b':{'side':'under','point':Decimal('3.5'),'selected_participant_id':None}}
        with self.assertRaisesRegex(BindingError,'exact threshold'):
            _shape('totals',rows,('a','b'),True)

    def setUp(self):
        self.snapshot = normalize_featured_payload(FIXTURE.read_bytes(), received_at=NOW)
        self.markets, self.books = synthetic_routes(self.snapshot)

    def test_all_six_keys_bind_without_merging_direction(self):
        bound = bind_snapshot(self.snapshot, markets=self.markets, books=self.books)
        self.assertEqual(25, len(bound))
        self.assertEqual(6, len({b.market_id for b in bound}))
        self.assertEqual(25, len({b.source_pointer for b in bound}))

    def test_unmapped_event_book_line_or_selection_fails(self):
        bad_routes = [self.markets[1:],
                      (replace(self.markets[0], provider_event_id='other'),) + self.markets[1:],
                      (replace(self.markets[0], selections=self.markets[0].selections[1:]),) + self.markets[1:]]
        for markets in bad_routes:
            with self.assertRaises(BindingError):
                bind_snapshot(self.snapshot, markets=markets, books=self.books)
        with self.assertRaises(BindingError):
            bind_snapshot(self.snapshot, markets=self.markets, books=self.books[1:])
        spread = next(m for m in self.markets if m.market_key == 'spreads')
        changed = replace(spread, selections=(replace(spread.selections[0], point=Decimal('-2.5')), spread.selections[1]))
        with self.assertRaises(BindingError):
            bind_snapshot(self.snapshot, markets=tuple(changed if m == spread else m for m in self.markets), books=self.books)

    def test_ambiguous_or_collapsed_routes_fail(self):
        with self.assertRaises(BindingError):
            bind_snapshot(self.snapshot, markets=self.markets + self.markets[:1], books=self.books)
        changed = (self.markets[0], replace(self.markets[1], market_id=self.markets[0].market_id)) + self.markets[2:]
        with self.assertRaises(BindingError):
            bind_snapshot(self.snapshot, markets=changed, books=self.books)
        with self.assertRaises(BindingError):
            bind_snapshot(self.snapshot, markets=self.markets, books=self.books + self.books[:1])

    def test_missing_quote_does_not_remove_expected_outcome_route(self):
        reduced = replace(self.snapshot, quotes=self.snapshot.quotes[1:])
        self.assertEqual(24, len(bind_snapshot(reduced, markets=self.markets, books=self.books)))
        self.assertEqual(3, len(self.markets[0].selections))


@unittest.skipUnless(os.getenv('CORNER_TEST_DATABASE') == '1' and os.getenv('CORNER_TEST_CONCURRENCY') == '1',
                     'opt-in disposable featured persistence database')
class FeaturedStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg2
        from psycopg2 import sql
        from config import DB_CONFIG
        cls.database_name = 'corner_featured_test_' + uuid4().hex
        cls.connection_config = dict(DB_CONFIG)
        cls.connection_config.pop('database', None)
        cls.connection_config['dbname'] = cls.database_name
        admin = psycopg2.connect(**DB_CONFIG)
        admin.autocommit = True
        try:
            with admin.cursor() as cur:
                cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.database_name)))
        finally:
            admin.close()
        cls.addClassCleanup(cls.drop_database)
        conn = cls.connect()
        try:
            for migration in sorted((ROOT / 'db/migrations').glob('00[2-6]_*.sql')):
                with conn.cursor() as cur:
                    cur.execute(migration.read_text(encoding='utf-8'))
        finally:
            conn.close()

    @classmethod
    def connect(cls):
        import psycopg2
        return psycopg2.connect(**cls.connection_config)

    @classmethod
    def drop_database(cls):
        import psycopg2
        from psycopg2 import sql
        from config import DB_CONFIG
        if not cls.database_name.startswith('corner_featured_test_') or len(cls.database_name) != 53:
            raise AssertionError('unexpected disposable database')
        admin = psycopg2.connect(**DB_CONFIG)
        admin.autocommit = True
        try:
            with admin.cursor() as cur:
                cur.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.database_name)))
        finally:
            admin.close()

    def setUp(self):
        from corner.ingestion import (_fetch_id, _ensure_vocabulary, _resolve_sportsbook,
                                      _resolve_market, _resolve_outcome, _create_batch, _create_payload)
        self.conn = self.connect()
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        data = json.loads(FIXTURE.read_bytes())
        suffix = uuid4().hex
        for event in data:
            event['id'] += suffix
            event['sport_key'] += suffix
        self.raw = json.dumps(data).encode()
        self.snapshot = normalize_featured_payload(self.raw, received_at=NOW)
        self.markets, self.books = synthetic_routes(self.snapshot)
        # Explicit fixture registry; aliases, competition and scope are not inferred in the writer.
        with self.conn.cursor() as cur:
            self.provider = str(_fetch_id(cur, '''INSERT INTO corner.providers(code,display_name)
                VALUES ('the_odds_api','The Odds API') ON CONFLICT(code) DO UPDATE SET display_name=EXCLUDED.display_name RETURNING id''', ()))
            _ensure_vocabulary(cur, 'quote_states', 'active', 'Active')
            unknown = _ensure_vocabulary(cur, 'event_statuses', 'unknown', 'Unknown')
            participant_type = _ensure_vocabulary(cur, 'participant_types', 'competitor', 'Competitor')
            sport = _fetch_id(cur, 'INSERT INTO corner.sports(code,display_name) VALUES (%s,%s) RETURNING id', (suffix, 'Synthetic'))
            self.events, participants = {}, {}
            for event in data:
                competition = _fetch_id(cur, 'INSERT INTO corner.competitions(sport_id,code,display_name) VALUES (%s,%s,%s) RETURNING id',
                                       (sport, event['sport_key'], 'Synthetic'))
                event_id = _fetch_id(cur, 'INSERT INTO corner.events(competition_id,scheduled_start,event_status_id) VALUES (%s,%s,%s) RETURNING id',
                                    (competition, event['commence_time'], unknown))
                self.events[event['id']] = event_id
                cur.execute('INSERT INTO corner.competition_provider_identities(provider_id,competition_id,external_id) VALUES (%s,%s,%s)',
                            (self.provider,competition,event['sport_key']))
                cur.execute('INSERT INTO corner.event_provider_identities(provider_id,event_id,external_id) VALUES (%s,%s,%s)',
                            (self.provider,event_id,event['id']))
                names = {(q.selection_name, q.selection_side) for q in self.snapshot.quotes if q.event_id == event['id']
                         and q.selection_side in {'home','away','entrant'}}
                for name, side in names:
                    participant = _fetch_id(cur, 'INSERT INTO corner.participants(participant_type_id,display_name) VALUES (%s,%s) RETURNING id',
                                            (participant_type,name))
                    participants[(event['id'],name)] = participant
                    cur.execute('INSERT INTO corner.event_participants(event_id,participant_id,role) VALUES (%s,%s,%s)',
                                (event_id,participant,'competitor' if side == 'entrant' else side))
                    cur.execute('INSERT INTO corner.provider_participant_aliases(provider_id,competition_id,raw_name,participant_id) VALUES (%s,%s,%s,%s)',
                                (self.provider,competition,name,participant))
        books = [BookRoute(b.provider_bookmaker_key,str(_resolve_sportsbook(self.conn,self.provider,b.provider_bookmaker_key,b.provider_bookmaker_key)))
                 for b in self.books]
        routes = []
        for route in self.markets:
            outright = route.market_key.startswith('outrights')
            market_id = str(_resolve_market(self.conn,self.events[route.provider_event_id],MARKET_TYPES[route.market_key],
                                           'competition' if outright else 'full_game'))
            selections = []
            for selection in route.selections:
                quote = next(q for q in self.snapshot.quotes if q.event_id == route.provider_event_id and q.market_key == route.market_key
                             and (q.selection_name,q.point) == (selection.provider_name,selection.point))
                participant = participants.get((quote.event_id,quote.selection_name))
                outcome_id = str(_resolve_outcome(self.conn,market_id,participant,quote.selection_side,quote.point))
                selections.append(replace(selection,outcome_id=outcome_id))
            routes.append(replace(route,market_id=market_id,selections=tuple(selections)))
        self.markets, self.books = tuple(routes), tuple(books)
        self.bindings = bind_snapshot(self.snapshot,markets=self.markets,books=self.books)
        batch = _create_batch(self.conn,self.provider,{'source':'synthetic featured fixture'})
        self.payload_id = str(_create_payload(self.conn,batch,self.provider,NOW,self.raw))

    def ingest(self, **kwargs):
        return ingest_featured_payload(kwargs.pop('conn',self.conn),payload_id=self.payload_id,
                                      bindings=kwargs.pop('bindings',self.bindings),**kwargs)

    def count(self):
        with self.conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM corner.odds_observations WHERE provider_payload_id=%s',(self.payload_id,))
            return cur.fetchone()[0]

    def read(self, bindings=None, at=NOW):
        pairs = tuple((b.outcome_id,b.sportsbook_id) for b in (bindings or self.bindings))
        return read_featured_streams(self.conn,streams=pairs,assessed_at=at,max_age=timedelta(seconds=30))

    def test_all_markets_persist_and_replay_exactly(self):
        first = self.ingest()
        self.assertEqual(25,self.count())
        self.assertEqual(first,self.ingest(bindings=tuple(reversed(self.bindings))))
        self.assertEqual(first.observation_ids,tuple(q.observation_id for q in self.read()))
        self.assertTrue(all(q.reason is None for q in self.read()))
        self.assertTrue(all(q.provider_payload_id==self.payload_id and q.source_record_key.startswith('featured-v1:')
                            for q in self.read()))
        with self.conn.cursor() as cur:
            cur.execute('SELECT DISTINCT mt.code FROM corner.odds_observations o JOIN corner.outcomes x ON x.id=o.outcome_id '
                        'JOIN corner.markets m ON m.id=x.market_id JOIN corner.market_types mt ON mt.id=m.market_type_id '
                        'WHERE o.provider_payload_id=%s',(self.payload_id,))
            self.assertEqual(set(MARKET_TYPES.values()),{row[0] for row in cur.fetchall()})

    def test_changed_replay_binding_conflicts(self):
        self.ingest()
        changed = (replace(self.bindings[0],outcome_id=self.bindings[1].outcome_id),)+self.bindings[1:]
        with self.assertRaises(FeaturedConflict):
            self.ingest(bindings=changed)
        self.assertEqual(25,self.count())

    def test_unmapped_or_wrong_canonical_outcome_leaves_no_partial_rows(self):
        for bindings in (self.bindings[:-1], (replace(self.bindings[-1],outcome_id=self.bindings[0].outcome_id),)+self.bindings[:-1]):
            with self.assertRaises(BindingError):
                self.ingest(bindings=bindings)
            self.assertEqual(0,self.count())

    def test_inactive_provider_mapping_rejected(self):
        with self.conn.cursor() as cur:
            cur.execute('UPDATE corner.sportsbook_provider_identities SET active=false WHERE sportsbook_id=%s',(self.books[0].sportsbook_id,))
        with self.assertRaises(BindingError):
            self.ingest()
        self.assertEqual(0,self.count())

    def test_replay_does_not_re_resolve_changed_aliases(self):
        first = self.ingest()
        with self.conn.cursor() as cur:
            cur.execute('UPDATE corner.provider_participant_aliases SET participant_id=NULL WHERE provider_id=%s',(self.provider,))
        self.assertEqual(first,self.ingest())

    def test_missing_and_stale_and_future_streams_remain_explicit(self):
        self.assertTrue(all(q.reason=='missing_trusted_observation' for q in self.read()))
        self.ingest()
        self.assertTrue(all(q.reason is None for q in self.read(at=NOW+timedelta(seconds=30))))
        self.assertTrue(all(q.reason=='stale_observation' for q in self.read(at=NOW+timedelta(seconds=31))))
        self.assertTrue(all(q.reason=='future_observation' for q in self.read(at=NOW-timedelta(seconds=1))))

    def test_reader_obeys_disposition(self):
        from corner.dispositions import DecisionAuthority,DispositionCommand,record_disposition
        first = self.ingest()
        record_disposition(self.conn,authority=DecisionAuthority('service','synthetic'),
                           command=DispositionCommand(str(uuid4()),first.observation_ids[0],'rejected','test',NOW))
        rows = self.read()
        self.assertEqual('missing_trusted_observation',rows[0].reason)
        self.assertEqual(24,sum(q.reason is None for q in rows))

    def test_new_unavailable_does_not_fall_back_to_active(self):
        first = self.ingest()
        with self.conn.cursor() as cur:
            cur.execute("INSERT INTO corner.quote_states(code,display_name) VALUES ('unavailable','Unavailable') ON CONFLICT DO NOTHING")
            cur.execute('''INSERT INTO corner.odds_observations(provider_payload_id,provider_id,outcome_id,sportsbook_id,
                quote_state_id,source_record_key,decimal_odds,observed_at)
                SELECT provider_payload_id,provider_id,outcome_id,sportsbook_id,
                (SELECT id FROM corner.quote_states WHERE code='unavailable'),'synthetic-unavailable',NULL,%s
                FROM corner.odds_observations WHERE id=%s RETURNING id''',(NOW+timedelta(seconds=1),first.observation_ids[0]))
            unavailable = str(cur.fetchone()[0])
        row = self.read(at=NOW+timedelta(seconds=2))[0]
        self.assertEqual(unavailable,row.observation_id)
        self.assertIsNone(row.decimal_odds)
        self.assertEqual('quote_unavailable',row.reason)

    def test_read_only_transaction_can_read(self):
        self.ingest()
        self.conn.commit()
        with self.conn.cursor() as cur:
            cur.execute('SET TRANSACTION READ ONLY')
        self.assertEqual(25,len(self.read()))

    def test_outer_rollback_removes_all_new_observations(self):
        self.conn.commit()
        self.ingest()
        self.conn.rollback()
        self.assertEqual(0,self.count())

    def test_sql_failure_mid_write_rolls_back_whole_ingestion(self):
        import psycopg2
        from psycopg2 import sql
        with self.conn.cursor() as cur:
            # Fail on the last quote, after earlier INSERTs have actually executed.
            cur.execute(sql.SQL('''CREATE FUNCTION corner.featured_test_fail() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN IF NEW.source_record_key={} THEN RAISE EXCEPTION 'synthetic failure'; END IF; RETURN NEW; END; $$''')
                .format(sql.Literal('featured-v1:'+self.bindings[-1].source_pointer)))
            cur.execute('CREATE TRIGGER featured_test_fail BEFORE INSERT ON corner.odds_observations '
                        'FOR EACH ROW EXECUTE FUNCTION corner.featured_test_fail()')
        with self.assertRaises(psycopg2.Error):
            self.ingest()
        self.assertEqual(0,self.count())

    def test_price_precision_is_not_silently_rounded(self):
        from corner.ingestion import _create_batch,_create_payload
        raw = self.raw.replace(b'"price": 3.4',b'"price": 3.4000001',1)
        batch = _create_batch(self.conn,self.provider,{'source':'synthetic extra precision'})
        self.payload_id = str(_create_payload(self.conn,batch,self.provider,NOW,raw))
        with self.assertRaisesRegex(BindingError,'represented exactly'):
            self.ingest()
        self.assertEqual(0,self.count())

    def test_payload_digest_mismatch_rejected(self):
        with self.conn.cursor() as cur:
            cur.execute('''INSERT INTO corner.provider_payloads
                (ingestion_batch_id,provider_id,received_at,http_status,payload_sha256,raw_body)
                SELECT ingestion_batch_id,provider_id,received_at,http_status,%s,raw_body
                FROM corner.provider_payloads WHERE id=%s RETURNING id''',(bytes(32),self.payload_id))
            self.payload_id = str(cur.fetchone()[0])
        with self.assertRaisesRegex(BindingError,'digest mismatch'):
            self.ingest()
        self.assertEqual(0,self.count())

    def inputs(self,key='h2h',with_lay=False,**changes):
        from corner.featured_queries import read_calculation_inputs
        route = next(m for m in self.markets if m.market_key==key)
        kwargs = dict(market_id=route.market_id,outcome_ids=tuple(s.outcome_id for s in route.selections),
            sportsbook_ids=tuple(b.sportsbook_id for b in self.books),assessed_at=NOW,max_age=timedelta(seconds=30),
            max_input_skew=timedelta(seconds=10),settlement_identity='synthetic-compatible-rules-v1',refund_possible=True,
            commissions={b.sportsbook_id:Decimal('0.02') if b.provider_bookmaker_key=='demo_exchange' else Decimal('0') for b in self.books})
        if with_lay:
            kwargs['lay_market_id']=next(m.market_id for m in self.markets if m.market_key==key+'_lay')
        return read_calculation_inputs(self.conn,**(kwargs|changes))

    def start_read_snapshot(self):
        self.ingest()
        self.conn.commit()
        self.conn.set_session(isolation_level='REPEATABLE READ',readonly=True)

    def test_database_quotes_feed_all_back_and_lay_calculators(self):
        self.start_read_snapshot()
        for key in ('h2h','spreads','totals','outrights'):
            with self.subTest(key=key):
                data = self.inputs(key,with_lay=key in {'h2h','outrights'})
                result = data.back_cover(total_stake=Decimal('300'))
                self.assertEqual(Decimal('40') if key=='h2h' else Decimal('15'),result.minimum_decisive_profit)
                self.assertFalse(result.availability_verified)
                self.assertTrue(any(s.reason=='missing_trusted_observation' for s in data.streams))
                if key in {'h2h','outrights'}:
                    back = next(o for o in data.offers if o.market_key==key)
                    lay = next(o for o in data.offers if o.market_key==key+'_lay' and o.selection_id==back.selection_id)
                    hedge = data.back_lay(back_quote_id=back.quote_id,lay_quote_id=lay.quote_id,back_stake=Decimal('100'))
                    self.assertGreater(hedge.lay_liability,0)

    def test_query_rejects_missing_draw_and_unknown_commission(self):
        self.start_read_snapshot()
        route = next(m for m in self.markets if m.market_key=='h2h')
        with self.assertRaisesRegex(BindingError,'omits registered'):
            self.inputs(outcome_ids=tuple(s.outcome_id for s in route.selections if s.provider_name!='Draw'))
        with self.assertRaisesRegex(BindingError,'commission'):
            self.inputs(commissions={})

    def test_database_quotes_feed_ev_and_promo_and_reject_incomplete_refs(self):
        from corner.featured_promos import PromoTerms
        from corner.featured_tools import ToolInputError
        self.start_read_snapshot()
        refs = tuple(b.sportsbook_id for b in self.books if b.provider_bookmaker_key != 'demo_exchange')
        terms = PromoTerms('synthetic:terms', 'bonus_stake_not_returned', Decimal('10'), Decimal('10'),
                           Decimal('1.5'), Decimal('0'), 'synthetic:eligibility', True)
        for key in ('h2h', 'outrights'):
            data = self.inputs(key, with_lay=True)
            back = next(o for o in data.offers if o.market_key == key)
            lay = next(o for o in data.offers if o.market_key == key+'_lay' and o.selection_id == back.selection_id)
            if key == 'h2h':
                result = data.expected_value(target_quote_id=lay.quote_id, required_reference_books=refs, stake=Decimal('10'))
                self.assertEqual(len(data.market.selection_ids), len(result.conditional_probabilities))
                self.assertEqual(2, len(result.reference_books))
                self.assertIsNone(result.unconditional_ev_ratio)
            else:
                # The retained outright fixture only has one back book; the
                # query bridge must NOT shrink the required reference population.
                with self.assertRaisesRegex(ToolInputError, 'incomplete or duplicate reference'):
                    data.expected_value(target_quote_id=lay.quote_id, required_reference_books=refs)
            converted = data.promo_conversion(back_quote_id=back.quote_id, lay_quote_id=lay.quote_id, terms=terms)
            self.assertGreater(converted.lay_liability, 0)
            self.assertFalse(converted.eligibility_verified)

    def test_stale_query_inputs_cannot_create_cover(self):
        from corner.featured_tools import ToolInputError
        self.start_read_snapshot()
        data = self.inputs(assessed_at=NOW+timedelta(seconds=31))
        self.assertEqual((),data.offers)
        with self.assertRaises(ToolInputError):
            data.back_cover(total_stake=Decimal('100'))

    def test_exact_spread_line_pairing(self):
        spread = next(m for m in self.markets if m.market_key=='spreads')
        # Inconsistent registry should be detected independently of odds availability.
        with self.conn.cursor() as cur:
            cur.execute('UPDATE corner.outcomes SET point=2.5 WHERE id=%s',(spread.selections[1].outcome_id,))
        self.conn.commit()
        self.conn.set_session(isolation_level='REPEATABLE READ',readonly=True)
        with self.assertRaisesRegex(BindingError,'exact opposites'):
            self.inputs('spreads')

    def test_lay_from_another_event_cannot_be_paired(self):
        wrong = next(m for m in self.markets if m.market_key=='outrights_lay')
        self.start_read_snapshot()
        with self.assertRaisesRegex(BindingError,'match event, scope and family'):
            self.inputs(with_lay=True,lay_market_id=wrong.market_id)

    def test_ambiguous_participant_alias_is_not_resolved_by_latest_row(self):
        with self.conn.cursor() as cur:
            cur.execute('''INSERT INTO corner.provider_participant_aliases(provider_id,competition_id,raw_name,participant_id)
                SELECT provider_id,competition_id,raw_name,NULL FROM corner.provider_participant_aliases
                WHERE provider_id=%s LIMIT 1''',(self.provider,))
        with self.assertRaisesRegex(BindingError,'ambiguous participant'):
            self.ingest()
        self.assertEqual(0,self.count())

    def test_skew_guard_does_not_choose_convenient_subset(self):
        first = self.ingest()
        with self.conn.cursor() as cur:
            cur.execute('''INSERT INTO corner.odds_observations(provider_payload_id,provider_id,outcome_id,sportsbook_id,
                quote_state_id,source_record_key,decimal_odds,observed_at)
                SELECT provider_payload_id,provider_id,outcome_id,sportsbook_id,quote_state_id,'synthetic-refresh',decimal_odds,%s
                FROM corner.odds_observations WHERE id=%s''',(NOW+timedelta(seconds=20),first.observation_ids[0]))
        self.conn.commit()
        self.conn.set_session(isolation_level='REPEATABLE READ',readonly=True)
        with self.assertRaisesRegex(BindingError,'maximum input skew'):
            self.inputs(assessed_at=NOW+timedelta(seconds=21))

    def test_future_provider_timestamp_is_retained_but_ineligible(self):
        first = self.ingest()
        with self.conn.cursor() as cur:
            cur.execute('''INSERT INTO corner.odds_observations(provider_payload_id,provider_id,outcome_id,sportsbook_id,
                quote_state_id,source_record_key,decimal_odds,observed_at,provider_updated_at)
                SELECT provider_payload_id,provider_id,outcome_id,sportsbook_id,quote_state_id,'synthetic-bad-time',decimal_odds,%s,%s
                FROM corner.odds_observations WHERE id=%s''',(NOW+timedelta(seconds=1),NOW+timedelta(seconds=2),first.observation_ids[0]))
        self.assertEqual('future_provider_timestamp',self.read(at=NOW+timedelta(seconds=3))[0].reason)

    def test_read_query_requires_coherent_read_only_transaction(self):
        with self.assertRaisesRegex(BindingError,'REPEATABLE READ'):
            self.inputs()
        self.conn.commit()
        self.conn.set_session(isolation_level='REPEATABLE READ',readonly=False)
        with self.assertRaisesRegex(BindingError,'READ ONLY'):
            self.inputs()

    def test_concurrent_same_payload_returns_original_ids(self):
        self.conn.commit()
        barrier = threading.Barrier(2)
        def write():
            conn = self.connect()
            try:
                barrier.wait(timeout=10)
                result = self.ingest(conn=conn)
                conn.commit()
                return result
            finally:
                conn.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(write) for _ in range(2)]
            receipts = [future.result(timeout=20) for future in futures]
        self.assertEqual(receipts[0],receipts[1])
        self.assertEqual(25,self.count())


if __name__ == '__main__':
    unittest.main()

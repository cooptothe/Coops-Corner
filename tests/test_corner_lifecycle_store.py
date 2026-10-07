"""011 real PostgreSQL tests. Every ordinary fixture transaction rolls back."""
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import test_corner_assessments as fixtures
import test_corner_assessment_concurrency as databases
from corner import lifecycle_store as s, channels as ch, assessments as a


class LifecycleDatabase(databases.AssessmentDatabase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        conn=cls.connect()
        try:
            with conn.cursor() as cur:
                cur.execute((Path(__file__).resolve().parents[1]/'db/migrations/011_corner_lifecycle_ledger.sql').read_text())
        finally:
            conn.close()


@unittest.skipUnless(os.getenv('CORNER_TEST_DATABASE')=='1' and os.getenv('CORNER_TEST_CONCURRENCY')=='1',
                     'opt-in disposable lifecycle database')
class LifecycleStoreTests(LifecycleDatabase,unittest.TestCase):
    select=fixtures.AssessmentLedgerTests.select
    evaluate=fixtures.AssessmentLedgerTests.evaluate
    qualify=fixtures.AssessmentLedgerTests.qualify
    register=fixtures.AssessmentLedgerTests.register
    capture=fixtures.AssessmentLedgerTests.capture
    command=fixtures.AssessmentLedgerTests.command
    record=fixtures.AssessmentLedgerTests.record
    append=fixtures.AssessmentLedgerTests.append
    sql_error=fixtures.AssessmentLedgerTests.sql_error

    def setUp(self):
        with patch('db.insert.connect',side_effect=self.connect):
            fixtures.AssessmentLedgerTests.setUp(self)
        self.condition=s.resolve_condition(self.conn,sportsbook_id=self.book_id,outcome_id=self.outcome_id,channel_id=self.channel['id'])
        self.activation=ch.activate_generation(self.conn,authority=self.authority,activation_key=str(uuid4()),
            command=ch.ActivationCommand(self.channel['id'],self.generation['id'],None,self.time-timedelta(minutes=1)))
        self.occurrence=ch.create_occurrence(self.conn,qualification_decision_id=self.judgment['id'])
        self.assessment=self.record()

    def app(self,kind,evidence=None,*,key=None,generation=None,at=None,conn=None,condition=None):
        evidence=evidence or {'generation_activation':self.activation,'evaluation':self.evaluation,
                             'qualification':self.judgment,'assessment':self.assessment}[kind]
        if at is None and kind in {'qualification','generation_activation'}:
            at=self.time if kind=='generation_activation' else self.time+timedelta(hours=3)
        return s.apply_command(conn or self.conn,authority=self.authority,application_key=key or str(uuid4()),
            command=s.ApplicationCommand((condition or self.condition)['id'],kind,evidence['id'],
                (generation or self.generation)['id'],at))

    def opened(self):
        self.app('generation_activation'); self.app('evaluation'); self.app('qualification')
        return self.app('assessment')

    def verify(self):
        return s.verify_history(self.conn,condition_id=self.condition['id'])

    def projections(self):
        from psycopg2.extras import RealDictCursor
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT * FROM corner.condition_processing_projections WHERE condition_id=%s',(self.condition['id'],))
            processing=cur.fetchone()
            cur.execute('SELECT * FROM corner.opportunities WHERE condition_id=%s ORDER BY opened_at,id',(self.condition['id'],))
            episodes=cur.fetchall()
        def clean(row): return {k:v for k,v in row.items() if k!='projected_at'} if row else None
        return clean(processing),[clean(row) for row in episodes]

    def test_uninitialized_condition_cannot_accept_evaluation(self):
        with self.assertRaises(s.HistoryCorruption): self.app('evaluation')
        self.assertEqual(0,self.verify()['applications'])
        self.assertEqual((None,[]),self.projections())

    def test_open_incremental_equals_full_replay_and_rebuild(self):
        opened=self.opened()
        before=self.projections()
        verified=self.verify()
        self.assertEqual(4,verified['applications'])
        self.assertEqual(bytes(opened['post_state_sha256']).hex(),verified['post_state_sha256'])
        with self.conn.cursor() as cur:
            cur.execute('DELETE FROM corner.condition_processing_projections WHERE condition_id=%s',(self.condition['id'],))
            cur.execute('DELETE FROM corner.opportunities WHERE condition_id=%s',(self.condition['id'],))
        self.assertEqual(verified,s.rebuild_projections(self.conn,condition_id=self.condition['id']))
        self.assertEqual(before,self.projections())
        again=self.app('evaluation')
        self.assertEqual(5,again['application_sequence'])
        self.assertEqual('already_reflected',again['application_outcome'])
        self.verify()

    def test_retry_returns_original_after_later_applications_without_reducer(self):
        original=self.app('generation_activation',key='original')
        self.app('evaluation'); self.app('qualification'); self.app('assessment')
        with patch.object(s,'_input',side_effect=AssertionError('retry cannot reload/reduce')):
            self.assertEqual(original,self.app('generation_activation',key='original'))
        with self.assertRaises(s.ApplicationConflict): self.app('evaluation',key='original')

    def test_new_key_same_assessment_has_receipt_but_no_transition(self):
        self.opened()
        duplicate=self.app('assessment')
        self.assertEqual('already_reflected',duplicate['application_outcome'])
        self.assertEqual(0,duplicate['transition_count'])
        self.verify()

    def test_accepted_refresh_is_zero_output_and_old_expiry_is_obsolete(self):
        self.opened()
        command=self.command(basis_assessment_id=self.assessment['id'])
        fresh=self.record(command,key='fresh')
        result=self.app('assessment',fresh)
        self.assertEqual('applied',result['application_outcome'])
        self.assertEqual(0,result['transition_count'])
        old_expiry=self.record(replace(command,assessed_at=command.assessed_at+timedelta(days=36501)),key='old-expiry')
        ignored=self.app('assessment',old_expiry)
        self.assertEqual('obsolete_binding',ignored['reason_code'])
        self.assertIsNotNone(self.projections()[0]['open_episode_id'])
        self.verify()

    def test_close_reopen_and_closed_episode_retention(self):
        opening=self.opened(); first=opening['result_snapshot']['outputs'][0]['episode_id']
        command=self.command(basis_assessment_id=self.assessment['id'])
        closed_assessment=self.record(replace(command,assessed_at=command.assessed_at+timedelta(seconds=1),
            capture_json=command.capture_json.replace('"phase":"pregame"','"phase":"live"')),key='live')
        closed=self.app('assessment',closed_assessment)
        self.assertEqual('unsupported_phase',closed['result_snapshot']['outputs'][0]['reason_code'])
        reopen_command=self.command(basis_assessment_id=closed_assessment['id'])
        reopened_assessment=self.record(replace(reopen_command,assessed_at=closed_assessment['assessed_at']+timedelta(seconds=1)),key='pregame')
        reopened=self.app('assessment',reopened_assessment)
        self.assertNotEqual(first,reopened['result_snapshot']['outputs'][0]['episode_id'])
        before=self.projections()
        self.assertEqual(2,len(before[1]))
        self.assertIsNotNone(before[1][0]['closed_at'])
        self.verify()
        s.rebuild_projections(self.conn,condition_id=self.condition['id'])
        self.assertEqual(before,self.projections())

    def test_rollover_preserves_condition_sequence_and_old_episode_generation(self):
        opening=self.opened()
        gen=self.register()
        at=self.assessment['assessed_at']+timedelta(seconds=1)
        activation=ch.activate_generation(self.conn,authority=self.authority,activation_key='next',
            command=ch.ActivationCommand(self.channel['id'],gen['id'],self.generation['id'],at))
        result=self.app('generation_activation',activation,generation=gen,at=at)
        self.assertEqual(5,result['application_sequence'])
        self.assertEqual(self.generation['id'],result['result_snapshot']['outputs'][0]['episode_generation_id'])
        self.assertEqual(gen['id'],self.projections()[0]['processed_generation_id'])
        self.verify()

    def test_negative_newer_judgment_closes_and_old_evaluation_cannot_rewind(self):
        self.opened()
        # A genuinely later evaluation with lower offered price, same configuration.
        self.append(self.target_id,price='1.01')
        evaluation=self.evaluate(evaluated_at=self.time+timedelta(seconds=2))
        judgment=self.qualify(evaluation)
        result=self.app('qualification',judgment,at=self.assessment['assessed_at']+timedelta(seconds=1))
        self.assertEqual('qualification_lost',result['result_snapshot']['outputs'][0]['reason_code'])
        self.app('evaluation')
        self.verify()

    def test_failure_after_output_insert_leaves_no_partial_state(self):
        self.app('generation_activation'); self.app('qualification')
        before=self.projections()
        with patch.object(s,'_project',side_effect=RuntimeError('fault injection')):
            with self.assertRaises(RuntimeError): self.app('assessment')
        self.assertEqual(before,self.projections())
        self.assertEqual(2,self.verify()['applications'])

    def test_history_rows_are_immutable(self):
        self.opened()
        for table in ('lifecycle_applications','opportunity_transitions'):
            for sql in (f'UPDATE corner.{table} SET id=id',f'DELETE FROM corner.{table}',f'TRUNCATE corner.{table} CASCADE'):
                self.sql_error(sql,(), 'P0001')

    def test_same_key_other_condition_conflicts(self):
        self.app('generation_activation',key='one')
        other=s.resolve_condition(self.conn,sportsbook_id=self.reference_ids[0],outcome_id=self.outcome_id,channel_id=self.channel['id'])
        with self.assertRaises(s.ApplicationConflict): self.app('generation_activation',key='one',condition=other)

    def test_changed_retry_time_or_context_conflicts(self):
        self.app('generation_activation',key='original')
        with self.assertRaises(s.ApplicationConflict):
            self.app('generation_activation',key='original',at=self.time+timedelta(seconds=1))
        with self.assertRaises(s.ApplicationConflict):
            s.apply_command(self.conn,authority=self.authority,application_key='original',command=s.ApplicationCommand(
                self.condition['id'],'generation_activation',self.activation['id'],self.generation['id'],self.time,'{"other":true}'))

    def test_unavailable_and_changed_prices_close_without_fallback(self):
        for state,price,reason in [('unavailable',None,'target_unavailable'),('active','1.50','analytical_evidence_changed')]:
            with self.subTest(state=state):
                with self.conn.cursor() as cur: cur.execute('SAVEPOINT subcase')
                self.opened()
                self.append(self.target_id,state=state,price=price)
                assessment=self.record(self.command(basis_assessment_id=self.assessment['id']),key='changed')
                receipt=self.app('assessment',assessment)
                self.assertEqual(reason,receipt['result_snapshot']['outputs'][0]['reason_code'])
                self.verify()
                with self.conn.cursor() as cur: cur.execute('ROLLBACK TO SAVEPOINT subcase')

    def test_uncertainty_advances_watermark_without_closing(self):
        self.opened()
        # Same quotes, but observation-age rejection at a later evaluation instant.
        evaluation=self.evaluate(evaluated_at=self.time+timedelta(days=1))
        self.assertEqual('not_evaluable',evaluation['result_kind'])
        receipt=self.app('evaluation',evaluation)
        self.assertEqual(0,receipt['transition_count'])
        self.assertEqual(evaluation['id'],self.projections()[0]['evaluation_watermark_id'])
        self.assertEqual(self.judgment['id'],self.projections()[0]['latest_threshold_qualification_id'])
        self.assertIsNotNone(self.projections()[0]['open_episode_id'])
        self.verify()

    def test_distinct_equivalent_qualification_does_not_duplicate_transition(self):
        self.opened()
        equivalent=self.qualify(self.evaluation)
        ch.create_occurrence(self.conn,qualification_decision_id=equivalent['id'])
        receipt=self.app('qualification',equivalent,at=self.assessment['assessed_at'])
        self.assertEqual('historical_or_equivalent',receipt['reason_code'])
        self.verify()

    def test_incremental_path_does_not_call_full_replay(self):
        self.opened()
        with patch.object(s,'_replay',side_effect=AssertionError('no full replay in write path')):
            self.app('evaluation')
        self.verify()

    def test_projection_corruption_cannot_become_authoritative(self):
        self.opened()
        with self.conn.cursor() as cur:
            cur.execute('UPDATE corner.condition_processing_projections SET accepted_assessment_id=NULL WHERE condition_id=%s',(self.condition['id'],))
        with self.assertRaises(s.HistoryCorruption): self.app('evaluation')
        s.rebuild_projections(self.conn,condition_id=self.condition['id'])
        self.assertEqual(self.assessment['id'],self.projections()[0]['accepted_assessment_id'])
        self.app('evaluation')

    def test_continue_and_rollover_match_full_replay_exactly(self):
        first=self.opened()['result_snapshot']['outputs'][0]
        evaluation=self.evaluate(evaluated_at=self.time+timedelta(seconds=3))
        judgment=self.qualify(evaluation)
        occurrence=ch.create_occurrence(self.conn,qualification_decision_id=judgment['id'])
        self.app('qualification',judgment,at=self.assessment['assessed_at'])
        command=self.command(qualification_decision_id=judgment['id'],evaluation_watermark_id=evaluation['id'],
            basis_assessment_id=self.assessment['id'])
        assessment=self.record(command,key='continue')
        continuation=self.app('assessment',assessment)['result_snapshot']['outputs'][0]
        self.assertEqual('continued',continuation['transition_kind'])
        self.assertEqual(first['episode_id'],continuation['episode_id'])
        self.assertEqual(occurrence['id'],self.projections()[1][0]['current_occurrence_id'])
        self.verify()
        # Activation at current time requires fresh post-activation evaluations.
        gen=self.register()
        at=assessment['assessed_at']+timedelta(seconds=1)
        activation=ch.activate_generation(self.conn,authority=self.authority,activation_key='rollover',
            command=ch.ActivationCommand(self.channel['id'],gen['id'],self.generation['id'],at))
        self.app('generation_activation',activation,generation=gen,at=at)
        # A persisted qualification already bound in history cannot acquire a
        # different generation by changing the application envelope.
        with self.assertRaises(ValueError): self.app('qualification',judgment,generation=gen,at=at)
        new_judgment=self.qualify(evaluation)
        ch.create_occurrence(self.conn,qualification_decision_id=new_judgment['id'])
        old=self.app('qualification',new_judgment,generation=gen,at=at)
        self.assertEqual('evaluation_predates_generation',old['reason_code'])
        self.assertIsNone(self.projections()[0]['open_episode_id'])
        before=self.projections()
        self.verify()
        s.rebuild_projections(self.conn,condition_id=self.condition['id'])
        self.assertEqual(before,self.projections())

    def test_uncertainty_cannot_reopen_from_old_threshold(self):
        self.opened()
        command=self.command(basis_assessment_id=self.assessment['id'])
        closed=self.record(replace(command,capture_json=command.capture_json.replace('"phase":"pregame"','"phase":"live"')),key='close')
        self.app('assessment',closed)
        evaluation=self.evaluate(evaluated_at=self.time+timedelta(days=1))
        self.app('evaluation',evaluation)
        command=self.command(basis_assessment_id=closed['id'],evaluation_watermark_id=evaluation['id'])
        historical=self.record(command,key='old-qualified')
        receipt=self.app('assessment',historical)
        self.assertEqual('obsolete_analytical_evidence',receipt['reason_code'])
        self.assertEqual(0,receipt['transition_count'])
        self.assertIsNone(self.projections()[0]['open_episode_id'])
        self.verify()

    def test_chain_constraint_rejects_wrong_predecessor_sequence_and_digest(self):
        self.opened()
        # Clone a valid receipt under a new command key, changing only chain fields.
        # This deliberately bypasses the API to exercise the database backstop.
        with self.conn.cursor() as cur:
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='corner' AND table_name='lifecycle_applications' ORDER BY ordinal_position")
            columns=[row[0] for row in cur.fetchall()]
        def clone(overrides):
            select=[]
            for column in columns:
                select.append(overrides.get(column,'src.'+column))
            return ('INSERT INTO corner.lifecycle_applications ('+','.join(columns)+') SELECT '+','.join(select)+
                ' FROM corner.lifecycle_applications src WHERE condition_id=%s AND application_sequence=4')
        base={'id':'uuidv7()','application_key':"'chain-test'",'application_sequence':'5',
              'previous_application_id':'src.id','previous_application_sequence':'4','pre_state_sha256':'src.post_state_sha256'}
        self.sql_error(clone(base|{'previous_application_sequence':'3'}),(self.condition['id'],),'23514')
        self.sql_error(clone(base|{'pre_state_sha256':"decode(repeat('00',32),'hex')"}),(self.condition['id'],),'23503')

    def test_opening_uniqueness_and_output_ordinal_shape(self):
        opened=self.opened()
        self.sql_error('''INSERT INTO corner.opportunity_transitions
            (application_id,output_ordinal,episode_id,episode_generation_id,transition_kind,reason_code,transition_at,
             opportunity_occurrence_id,actionability_assessment_id)
            SELECT application_id,2,episode_id,episode_generation_id,transition_kind,reason_code,transition_at,
             opportunity_occurrence_id,actionability_assessment_id FROM corner.opportunity_transitions WHERE application_id=%s''',
            (opened['id'],),'23505')

    def test_cross_channel_and_wrong_condition_evidence_fail_atomically(self):
        self.app('generation_activation')
        other=s.resolve_condition(self.conn,sportsbook_id=self.reference_ids[0],outcome_id=self.outcome_id,channel_id=self.channel['id'])
        self.app('generation_activation',condition=other)
        with self.assertRaises(ValueError): self.app('evaluation',condition=other)
        self.assertEqual(1,self.verify()['applications'])

    def test_rebuild_failure_during_replacement_preserves_original_projections(self):
        self.opened(); before=self.projections()
        original=s._project
        def fail(cur,row):
            original(cur,row)
            if row['application_sequence']==2: raise RuntimeError('rebuild fault')
        with patch.object(s,'_project',side_effect=fail):
            with self.assertRaises(RuntimeError): s.rebuild_projections(self.conn,condition_id=self.condition['id'])
        self.assertEqual(before,self.projections())

    def test_replay_does_not_consult_current_quotes(self):
        self.opened()
        self.append(self.target_id,price='9.99')
        with patch.object(a,'capture_assessment',side_effect=AssertionError('no recapture')):
            self.verify()
            s.rebuild_projections(self.conn,condition_id=self.condition['id'])

    def test_backdated_close_rolls_back(self):
        self.opened()
        gen=self.register()
        activation=ch.activate_generation(self.conn,authority=self.authority,activation_key='backdated',
            command=ch.ActivationCommand(self.channel['id'],gen['id'],self.generation['id'],self.time+timedelta(seconds=1)))
        with self.assertRaises(ValueError):
            self.app('generation_activation',activation,generation=gen,at=self.time+timedelta(seconds=2))
        self.assertEqual(4,self.verify()['applications'])

    def test_projection_composite_keys_reject_false_claims(self):
        self.opened()
        self.sql_error('UPDATE corner.condition_processing_projections SET last_application_sequence=999 WHERE condition_id=%s',
            (self.condition['id'],),'23503')
        self.sql_error('UPDATE corner.opportunities SET id=%s WHERE condition_id=%s',(str(uuid4()),self.condition['id']),'23503')
        self.sql_error('UPDATE corner.condition_processing_projections SET open_episode_id=NULL WHERE condition_id=%s',
            (self.condition['id'],),'23514')

    def test_missing_transition_fails_rebuild_without_replacing_projections(self):
        self.opened(); before=self.projections()
        # Controlled verifier fault injection; do not disable ledger protections.
        original=s._transition_doc
        with patch.object(s,'_transition_doc',side_effect=lambda row: original(row)|{'reason_code':'corrupt'}):
            with self.assertRaises(s.HistoryCorruption): s.rebuild_projections(self.conn,condition_id=self.condition['id'])
        self.assertEqual(before,self.projections())

    def race(self,*,same_key=False,changed=False,other_condition=False):
        self.app('generation_activation')
        self.conn.commit()
        barrier=threading.Barrier(2)
        def worker(number):
            conn=self.connect()
            try:
                with conn.cursor() as cur: cur.execute("SET LOCAL statement_timeout='15s'")
                barrier.wait(timeout=10)
                condition=self.condition
                if other_condition and number:
                    condition=s.resolve_condition(conn,sportsbook_id=self.reference_ids[0],outcome_id=self.outcome_id,channel_id=self.channel['id'])
                kind='qualification' if changed and number else 'evaluation'
                if other_condition and number: kind='generation_activation'
                result=self.app(kind,key='race' if same_key else 'race-'+str(number),conn=conn,condition=condition)
                conn.commit()
                return result
            except s.ApplicationConflict as error:
                conn.rollback(); return error
            finally: conn.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(worker,(0,1)))

    def test_concurrent_distinct_commands_have_one_serial_order(self):
        results=self.race()
        self.assertEqual([2,3],sorted(r['application_sequence'] for r in results))
        self.assertEqual({'applied','already_reflected'},{r['application_outcome'] for r in results})
        self.verify()

    def test_concurrent_identical_command_returns_same_receipt(self):
        results=self.race(same_key=True)
        self.assertEqual(results[0],results[1])
        self.assertEqual(2,self.verify()['applications'])

    def test_concurrent_changed_command_has_domain_conflict(self):
        results=self.race(same_key=True,changed=True)
        self.assertEqual(1,sum(isinstance(v,s.ApplicationConflict) for v in results))
        self.assertEqual(2,self.verify()['applications'])

    def test_concurrent_cross_condition_key_conflicts(self):
        results=self.race(same_key=True,other_condition=True)
        self.assertEqual(1,sum(isinstance(v,s.ApplicationConflict) for v in results))
        self.verify()

    def test_concurrent_first_condition_and_initialization_share_one_lock_anchor(self):
        self.conn.commit()
        barrier=threading.Barrier(2)
        def worker(number):
            conn=self.connect()
            try:
                with conn.cursor() as cur: cur.execute("SET LOCAL statement_timeout='15s'")
                barrier.wait(timeout=10)
                condition=s.resolve_condition(conn,sportsbook_id=self.reference_ids[0],outcome_id=self.outcome_id,channel_id=self.channel['id'])
                result=self.app('generation_activation',condition=condition,key='first-'+str(number),conn=conn)
                conn.commit()
                return condition,result
            finally: conn.close()
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(worker,(0,1)))
        self.assertEqual(results[0][0],results[1][0])
        self.assertEqual([1,2],sorted(r['application_sequence'] for _,r in results))
        s.verify_history(self.conn,condition_id=results[0][0]['id'])

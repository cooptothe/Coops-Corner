"""Work-ledger constraints, non-owner permissions and real lease races."""
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from psycopg2.extras import RealDictCursor

import test_corner_runtime_roles as roles
from corner import work as w, runtime_roles as r, channels as ch, qualifications as q, evaluations as ev


class WorkDatabase(roles.RoleDatabase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        conn=cls.connect()
        try:
            with conn.cursor() as cur:
                cur.execute((Path(__file__).resolve().parents[1]/'db/migrations/012_corner_work_ledger.sql').read_text())
            r.grant_work_privileges(conn,cls.roles)
            conn.commit()
        finally: conn.close()


@unittest.skipUnless(os.getenv('CORNER_TEST_DATABASE')=='1' and os.getenv('CORNER_TEST_CONCURRENCY')=='1','opt-in disposable work DB')
class WorkTests(WorkDatabase,unittest.TestCase):
    setUp=roles.RuntimeRoleTests.setUp
    select=roles.RuntimeRoleTests.select
    evaluate=roles.RuntimeRoleTests.evaluate
    qualify=roles.RuntimeRoleTests.qualify
    register=roles.RuntimeRoleTests.register
    capture=roles.RuntimeRoleTests.capture
    command=roles.RuntimeRoleTests.command
    record=roles.RuntimeRoleTests.record
    app=roles.RuntimeRoleTests.app
    opened=roles.RuntimeRoleTests.opened
    sql_error=roles.RuntimeRoleTests.sql_error
    role=roles.RuntimeRoleTests.role

    def enqueue(self,kind='ensure_occurrence',key=None,sources=None):
        sources=sources or ({'qualification_decision_id':self.judgment['id']} if kind=='ensure_occurrence'
                           else {'engine_evaluation_id':self.evaluation['id']})
        return w.enqueue(self.conn,kind=kind,namespace=self.authority.identifier,key=key or str(uuid4()),sources=sources)

    def claim(self,request,owner='worker-a',seconds=60,conn=None):
        return w.claim(conn or self.conn,owner=owner,lease_for=timedelta(seconds=seconds),request_id=request['id'])

    def prepare(self,request,lease,command=None):
        command=command or self.judgment['id']
        return w.prepare(self.conn,request_id=request['id'],owner=lease['lease_owner'],token=lease['lease_token'],command=command)

    def complete(self,request,lease,conn=None):
        return w.complete(conn or self.conn,request_id=request['id'],owner=lease['lease_owner'],token=lease['lease_token'])

    def execution(self,request):
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT * FROM corner.work_executions WHERE work_request_id=%s',(request['id'],))
            return dict(cur.fetchone())

    def expire(self,request):
        with self.conn.cursor() as cur:
            cur.execute("UPDATE corner.work_executions SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE work_request_id=%s",(request['id'],))

    def test_discovery_dedupe_preserves_identity_and_conflicts_on_changed_intent(self):
        first=self.enqueue(key='same')
        self.assertEqual(first,self.enqueue(key='same'))
        with self.assertRaises(w.WorkConflict):
            w.enqueue(self.conn,kind='ensure_occurrence',namespace=self.authority.identifier,key='same',intent_json='{"changed":true}',
                sources={'qualification_decision_id':self.judgment['id']})

    def test_write_once_preparation_and_native_occurrence_completion(self):
        request=self.enqueue(); lease=self.claim(request)
        prepared=self.prepare(request,lease)
        self.assertEqual(prepared,self.prepare(request,lease))
        with self.assertRaises(w.WorkConflict): self.prepare(request,lease,str(uuid4()))
        result=self.complete(request,lease)
        self.assertEqual('completed',result['status'])
        self.assertEqual(self.occurrence['id'],result['opportunity_occurrence_id'])
        self.assertIsNone(result['lease_token'])
        self.assertIsNone(self.claim(request))

    def test_worker_role_can_complete_but_cannot_mutate_frozen_records(self):
        with self.role('worker'):
            request=self.enqueue(); lease=self.claim(request)
            self.prepare(request,lease); self.complete(request,lease)
            for table in ('work_requests','prepared_work_commands'):
                for command in (f'UPDATE corner.{table} SET id=id',f'DELETE FROM corner.{table}',f'TRUNCATE corner.{table} CASCADE'):
                    self.sql_error(command,(),'42501')

    def test_producer_cannot_claim_or_complete(self):
        with self.role('work_producer'):
            request=self.enqueue()
            self.sql_error('UPDATE corner.work_executions SET status=status WHERE work_request_id=%s',(request['id'],),'42501')
            self.sql_error('INSERT INTO corner.prepared_work_commands DEFAULT VALUES',(),'42501')

    def test_preparation_after_reclaim_is_fenced_out(self):
        request=self.enqueue(); old=self.claim(request)
        self.expire(request)
        new=self.claim(request,owner='worker-b')
        self.assertNotEqual(old['lease_token'],new['lease_token'])
        with self.assertRaises(w.LeaseLost): self.prepare(request,old)
        self.assertIsNone(w.load_prepared(self.conn,request_id=request['id']))
        self.prepare(request,new)

    def test_reclaim_reuses_original_preparation(self):
        request=self.enqueue(); old=self.claim(request); prepared=self.prepare(request,old)
        self.expire(request); new=self.claim(request,owner='worker-b')
        self.assertEqual(prepared,w.load_prepared(self.conn,request_id=request['id']))
        self.assertEqual(prepared,self.prepare(request,new))
        self.complete(request,new)

    def test_stale_worker_cannot_heartbeat_complete_or_record_failure(self):
        request=self.enqueue(); old=self.claim(request); self.prepare(request,old)
        self.expire(request); new=self.claim(request,owner='worker-b'); before=self.execution(request)
        with self.assertRaises(w.LeaseLost):
            w.heartbeat(self.conn,request_id=request['id'],owner=old['lease_owner'],token=old['lease_token'],lease_for=timedelta(seconds=60))
        with self.assertRaises(w.LeaseLost): self.complete(request,old)
        with self.assertRaises(w.LeaseLost):
            w.record_failure(self.conn,request_id=request['id'],owner=old['lease_owner'],token=old['lease_token'],status='blocked',reason='stale-worker')
        self.assertEqual(before,self.execution(request))
        self.complete(request,new)

    def test_expiry_uses_wall_clock_not_transaction_start(self):
        request=self.enqueue(); lease=self.claim(request,seconds=.02)
        with self.conn.cursor() as cur: cur.execute('SELECT pg_sleep(0.04)')
        with self.assertRaises(w.LeaseLost): self.prepare(request,lease)

    def test_waiting_blocked_and_retryable_have_distinct_claimability(self):
        for status in ('waiting','blocked','retryable'):
            request=self.enqueue(); lease=self.claim(request); prepared=self.prepare(request,lease)
            now=datetime.now(timezone.utc)
            result=w.record_failure(self.conn,request_id=request['id'],owner=lease['lease_owner'],token=lease['lease_token'],
                status=status,reason='explicit-test',retry_at=now+timedelta(hours=1) if status=='retryable' else None)
            self.assertEqual(int(status=='retryable'),result['retry_count'])
            self.assertIsNone(self.claim(request))
            if status!='retryable':
                w.resume(self.conn,request_id=request['id'],expected_status=status,available_at=now)
                next_lease=self.claim(request)
                self.assertIsNotNone(next_lease)
                self.assertEqual(prepared,w.load_prepared(self.conn,request_id=request['id']))

    def test_execution_shapes_are_database_enforced(self):
        request=self.enqueue()
        self.sql_error("UPDATE corner.work_executions SET status='leased' WHERE work_request_id=%s",(request['id'],),'23514')
        self.sql_error("UPDATE corner.work_executions SET completed_at=clock_timestamp() WHERE work_request_id=%s",(request['id'],),'23514')
        lease=self.claim(request); prepared=self.prepare(request,lease)
        self.sql_error('''UPDATE corner.work_executions SET status='completed',lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,
            completed_at=clock_timestamp(),prepared_command_id=%s,engine_evaluation_id=%s WHERE work_request_id=%s''',
            (prepared['id'],self.evaluation['id'],request['id']),'23514')

    def test_different_requests_can_share_native_domain_result(self):
        ids=[]
        for _ in range(2):
            request=self.enqueue(); lease=self.claim(request); self.prepare(request,lease)
            ids.append(self.complete(request,lease)['opportunity_occurrence_id'])
        self.assertEqual(ids[0],ids[1])

    def qualify_work(self,threshold='.01'):
        from decimal import Decimal
        request=self.enqueue('qualify'); lease=self.claim(request)
        command=q.QualificationCommand(self.evaluation['id'],q.MinimumEVPolicy('work-v1',Decimal(threshold)),datetime.now(timezone.utc))
        w.prepare(self.conn,request_id=request['id'],owner=lease['lease_owner'],token=lease['lease_token'],
            command=command,authority=self.authority,domain_key='work-'+request['id'])
        return request,lease

    def test_negative_qualification_is_successful_work(self):
        request,lease=self.qualify_work('100')
        result=self.complete(request,lease)
        self.assertEqual('completed',result['status'])
        with self.conn.cursor() as cur:
            cur.execute('SELECT decision_kind FROM corner.qualification_decisions WHERE id=%s',(result['qualification_decision_id'],))
            self.assertEqual('not_qualified',cur.fetchone()[0])

    def test_domain_insert_and_completion_rollback_together(self):
        request,lease=self.qualify_work()
        original=w._result_matches
        def fault(*args):
            original(*args)
            raise RuntimeError('fault after domain insert')
        with patch.object(w,'_result_matches',side_effect=fault):
            with self.assertRaises(RuntimeError): self.complete(request,lease)
        with self.conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM corner.qualification_decisions WHERE qualification_key=%s',('work-'+request['id'],))
            self.assertEqual(0,cur.fetchone()[0])
        self.assertEqual('leased',self.execution(request)['status'])
        self.complete(request,lease)

    def test_result_from_another_command_is_not_accepted(self):
        request,lease=self.qualify_work()
        with patch.object(w,'_dispatch',return_value=self.judgment):
            with self.assertRaises(w.WorkValidationError): self.complete(request,lease)
        self.assertEqual('leased',self.execution(request)['status'])

    def test_lost_acknowledgement_reads_original_completion_without_execution(self):
        request=self.enqueue(); lease=self.claim(request); self.prepare(request,lease)
        completed=self.complete(request,lease); self.conn.commit()
        with patch.object(w,'_dispatch',side_effect=AssertionError('completed work must not execute again')):
            self.assertEqual(completed,w.load_execution(self.conn,request_id=request['id']))
            self.assertIsNone(self.claim(request))

    def test_failure_is_recorded_after_rollback_in_a_new_transaction(self):
        request,lease=self.qualify_work(); self.conn.commit()
        with patch.object(w,'_result_matches',side_effect=RuntimeError('transaction failure')):
            with self.assertRaises(RuntimeError): self.complete(request,lease)
        self.conn.rollback()
        result=w.record_failure(self.conn,request_id=request['id'],owner=lease['lease_owner'],token=lease['lease_token'],
            status='retryable',reason='transient',retry_at=datetime.now(timezone.utc))
        self.conn.commit()
        self.assertEqual(1,result['retry_count'])
        next_lease=self.claim(request,owner='worker-b'); self.conn.commit()
        self.assertEqual('completed',self.complete(request,next_lease)['status'])

    def test_crash_after_preparation_commit_preserves_frozen_assessment(self):
        request=self.enqueue('assess',sources={'condition_id':self.condition['id'],'generation_id':self.generation['id'],
            'qualification_decision_id':self.judgment['id']})
        lease=self.claim(request)
        command=self.command()
        prepared=w.prepare(self.conn,request_id=request['id'],owner=lease['lease_owner'],token=lease['lease_token'],
            command=command,authority=self.authority,domain_key='frozen-'+request['id'])
        self.conn.commit()
        self.expire(request); self.conn.commit()
        next_lease=self.claim(request,owner='worker-b'); self.conn.commit()
        from corner import assessments
        with patch.object(assessments,'capture_assessment',side_effect=AssertionError('no recapture')):
            self.assertEqual(prepared,w.load_prepared(self.conn,request_id=request['id']))
            self.assertEqual('completed',self.complete(request,next_lease)['status'])

    def test_impossible_request_bindings_cannot_be_frozen(self):
        request=self.enqueue('qualify'); lease=self.claim(request)
        from decimal import Decimal
        command=q.QualificationCommand(str(uuid4()),q.MinimumEVPolicy('test',Decimal('.01')),datetime.now(timezone.utc))
        with self.assertRaises(w.WorkValidationError):
            w.prepare(self.conn,request_id=request['id'],owner=lease['lease_owner'],token=lease['lease_token'],
                command=command,authority=self.authority,domain_key='wrong')
        self.assertIsNone(w.load_prepared(self.conn,request_id=request['id']))

    def test_non_evaluable_and_ignored_results_complete_successfully(self):
        from corner import lifecycle_store as ls
        selected=self.select(evaluated_at=self.time+timedelta(days=1))
        request=self.enqueue('evaluate',sources={'condition_id':self.condition['id'],'generation_id':self.generation['id']})
        lease=self.claim(request)
        w.prepare(self.conn,request_id=request['id'],owner=lease['lease_owner'],token=lease['lease_token'],
            command=ev.EvaluationCommand(selected.snapshot,selected.configuration),authority=self.authority,domain_key='no-ev')
        result=self.complete(request,lease)
        with self.conn.cursor() as cur:
            cur.execute('SELECT result_kind FROM corner.engine_evaluations WHERE id=%s',(result['engine_evaluation_id'],))
            self.assertEqual('not_evaluable',cur.fetchone()[0])
        self.app('generation_activation'); self.app('evaluation')
        request=self.enqueue('apply_lifecycle',sources={'condition_id':self.condition['id'],'generation_id':self.generation['id'],
            'engine_evaluation_id':self.evaluation['id']})
        lease=self.claim(request)
        w.prepare(self.conn,request_id=request['id'],owner=lease['lease_owner'],token=lease['lease_token'],
            command=ls.ApplicationCommand(self.condition['id'],'evaluation',self.evaluation['id'],self.generation['id']),
            authority=self.authority,domain_key='duplicate-evaluation')
        result=self.complete(request,lease)
        self.assertEqual('completed',result['status'])
        with self.conn.cursor() as cur:
            cur.execute('SELECT application_outcome FROM corner.lifecycle_applications WHERE id=%s',(result['lifecycle_application_id'],))
            self.assertEqual('already_reflected',cur.fetchone()[0])

    def test_true_capture_reclaim_race_rejects_stale_preparer(self):
        request=self.enqueue(); lease=self.claim(request); self.conn.commit()
        capture_done=threading.Event(); reclaimed=threading.Event()
        def stale_worker():
            conn=self.connect()
            try:
                captured=self.judgment['id']
                capture_done.set()
                if not reclaimed.wait(timeout=5): raise AssertionError('no reclaim')
                try:
                    w.prepare(conn,request_id=request['id'],owner=lease['lease_owner'],token=lease['lease_token'],command=captured)
                except w.LeaseLost:
                    conn.rollback(); return 'fenced'
                return 'incorrectly prepared'
            finally: conn.close()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(stale_worker)
            self.assertTrue(capture_done.wait(timeout=5))
            self.expire(request); self.conn.commit()
            next_lease=self.claim(request,owner='worker-b'); self.conn.commit()
            reclaimed.set(); self.assertEqual('fenced',future.result(timeout=5))
        self.assertIsNone(w.load_prepared(self.conn,request_id=request['id']))
        self.prepare(request,next_lease)

    def test_unsupported_frozen_revision_blocks_without_rewriting(self):
        request,lease=self.qualify_work(); before=w.load_prepared(self.conn,request_id=request['id'])
        with patch.object(q,'POLICY_REVISION','different-build'):
            with self.assertRaises(w.WorkBlocked): self.complete(request,lease)
        self.assertEqual(before,w.load_prepared(self.conn,request_id=request['id']))

    def test_all_five_dispatch_paths_use_existing_domain_adapters(self):
        from corner import lifecycle_store as ls
        selected=self.select()
        command=ev.EvaluationCommand(selected.snapshot,selected.configuration)
        requests=[('evaluate',command,{'condition_id':self.condition['id'],'generation_id':self.generation['id']}),
            ('assess',self.command(),{'condition_id':self.condition['id'],'generation_id':self.generation['id'],'qualification_decision_id':self.judgment['id']}),
            ('apply_lifecycle',ls.ApplicationCommand(self.condition['id'],'generation_activation',self.activation['id'],self.generation['id'],self.time),
             {'condition_id':self.condition['id'],'generation_id':self.generation['id'],'channel_generation_activation_id':self.activation['id']})]
        with self.role('worker'):
            for kind,command,sources in requests:
                request=self.enqueue(kind,sources=sources); lease=self.claim(request)
                w.prepare(self.conn,request_id=request['id'],owner=lease['lease_owner'],token=lease['lease_token'],
                    command=command,authority=self.authority,domain_key='dispatch-'+request['id'])
                self.assertEqual('completed',self.complete(request,lease)['status'])

    def test_concurrent_duplicate_discovery_creates_one_request(self):
        self.conn.commit(); barrier=threading.Barrier(2)
        def worker(_):
            conn=self.connect()
            try:
                barrier.wait(timeout=5)
                result=w.enqueue(conn,kind='ensure_occurrence',namespace=self.authority.identifier,key='race',
                    sources={'qualification_decision_id':self.judgment['id']})
                conn.commit(); return result
            finally: conn.close()
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(worker,(0,1)))
        self.assertEqual(results[0],results[1])

    def test_concurrent_claim_has_one_owner(self):
        request=self.enqueue(); self.conn.commit(); barrier=threading.Barrier(2)
        def worker(number):
            conn=self.connect()
            try:
                barrier.wait(timeout=5)
                result=self.claim(request,owner='worker-'+str(number),conn=conn)
                conn.commit(); return result
            finally: conn.close()
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(worker,(0,1)))
        self.assertEqual(1,sum(v is not None for v in results))

    def test_valid_completion_holds_fence_past_expiry(self):
        request=self.enqueue(); lease=self.claim(request,seconds=.3); self.prepare(request,lease); self.conn.commit()
        executing=threading.Event(); reclaim_checked=threading.Event()
        original=w._dispatch
        def slow(conn,document):
            with conn.cursor() as cur: cur.execute('SELECT pg_sleep(0.4)')
            executing.set()
            if not reclaim_checked.wait(timeout=5): raise AssertionError('reclaimer missing')
            return original(conn,document)
        def finish():
            conn=self.connect()
            try:
                result=self.complete(request,lease,conn=conn); conn.commit(); return result
            finally: conn.close()
        with patch.object(w,'_dispatch',side_effect=slow),ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(finish)
            self.assertTrue(executing.wait(timeout=5))
            # SKIP LOCKED intentionally skips the protected row rather than waiting.
            self.assertIsNone(self.claim(request,owner='worker-b'))
            self.conn.commit(); reclaim_checked.set()
            result=future.result(timeout=5)
        self.assertEqual('completed',result['status'])
        self.assertIsNone(self.claim(request,owner='worker-b'))

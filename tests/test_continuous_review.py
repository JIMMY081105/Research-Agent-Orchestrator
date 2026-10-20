"""Additional controller tests; mocks are explicit and all databases are isolated.
Run directly or copy into tests/test_continuous_review.py for canonical evidence.
"""
import concurrent.futures
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(r'E:\Github\Building-Generation-Validation')
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'tests'))
import test_system as baseline
from researchops import adapters, core, deployment
from researchops.core import System
from researchops.integrity import canonical, digest, manifest, read_json, write_json


class ContinuousReviewTests(unittest.TestCase):
    setUp = baseline.QueueTests.setUp
    tearDown = baseline.QueueTests.tearDown
    fake = baseline.QueueTests.fake
    submit = baseline.QueueTests.submit
    state = baseline.QueueTests.state
    audit_evidence = baseline.QueueTests.audit_evidence
    audit = baseline.QueueTests.audit
    revise = baseline.QueueTests.revise
    fake_activation = baseline.QueueTests.fake_activation
    cycle_task = baseline.QueueTests.cycle_task

    def seed_review(self, count, legacy=False):
        for i in range(count):
            if legacy:
                purpose = ('codex-audit-dev:' if i % 2 else 'independent-review:')+uuid.uuid4().hex*2
                self.system.db.execute('INSERT INTO calls VALUES(?,?,?,?)',
                    (str(uuid.uuid4()),core.utc()[:10],purpose,core.utc()))
            else:
                self.system.reserve('independent-review:'+uuid.uuid4().hex*2,
                                    engine='codex' if i % 2 else 'claude', stage='independent-review')
        self.system.db.commit()

    def authorize_continuous(self):
        self.fake_activation()
        cycle = str(uuid.uuid4())
        deployment.authorize_cycle(self.system,cycle,self.cycle_task(cycle),
            'User explicitly authorized continuous repairs and fifty shared reviews per UTC day.',
            'claude',continuous=True)
        return cycle

    def prepare_rework(self):
        tid=self.submit()
        self.mutate=lambda stage,value: ({**value,'verdict':'REWORK','issues':['Explain the measured sign correctly.']}
                                        if stage=='review' else value)
        self.system.tick();self.system.tick()
        self.assertEqual(self.state(tid)['state'],'REWORK')
        return tid,json.loads(self.state(tid)['spec'])

    def test_shared_fifty_includes_both_engines_and_historical_missing_metadata(self):
        self.seed_review(49,legacy=True)
        self.assertEqual(self.system.reviews_today(),49)
        self.assertEqual(self.system.db.execute('SELECT count(*) FROM call_engines').fetchone()[0],0)
        self.system.reserve(str(uuid.uuid4())+':review',engine='claude',stage='review')
        with self.assertRaises(adapters.CallError) as failure:
            self.system.reserve('cycle-review:'+uuid.uuid4().hex,engine='codex',stage='independent-review')
        self.assertEqual(failure.exception.kind,'REVIEW_BUDGET')
        self.assertEqual(self.system.reviews_today(),50)
        self.assertEqual(self.system.calls_today(),50)

    def test_execution_calls_do_not_consume_review_allowance(self):
        self.seed_review(50)
        for _ in range(55):
            self.system.reserve(str(uuid.uuid4())+':execute',engine='codex',stage='execute')
        self.assertEqual(self.system.reviews_today(),50)
        self.assertEqual(self.system.calls_today(),105)

    def test_nonreview_legacy_diagnostics_not_counted(self):
        for p in ('tool-event-diagnostic','codex-nonfatal-error-diagnostic',
                  'claude-2.1.302-opus-5-5-launch-verification'):
            self.system.db.execute('INSERT INTO calls VALUES(?,?,?,?)',
                (str(uuid.uuid4()),core.utc()[:10],p,core.utc()))
        self.system.db.commit()
        self.assertEqual(self.system.reviews_today(),0)
        self.assertEqual(self.system.calls_today(),3)

    def test_concurrent_review_reservations_never_make_fifty_one(self):
        self.seed_review(49,legacy=True)
        ready=threading.Barrier(2)
        def reserve(engine):
            other=System(self.source,self.runtime,self.fake)
            try:
                ready.wait(timeout=10)
                try:
                    other.reserve(str(uuid.uuid4())+':review',engine=engine,stage='review')
                    return 'CHARGED'
                except adapters.CallError as failure:
                    return failure.kind
            finally:
                other.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(reserve,engine) for engine in ('codex','claude')]
            outcomes=sorted(f.result(timeout=20) for f in futures)
        self.assertEqual(outcomes,['CHARGED','REVIEW_BUDGET'])
        self.assertEqual(self.system.reviews_today(),50)

    def test_review_cap_refusal_cannot_increment_cycle_allowance(self):
        cycle=self.authorize_continuous()
        self.seed_review(50,legacy=True)
        before=self.system.cycle(cycle)[0]['used'].copy()
        with self.assertRaises(adapters.CallError) as failure:
            self.audit('PASS',reviewer='claude',cycle=cycle)
        self.assertEqual(failure.exception.kind,'REVIEW_BUDGET')
        self.assertEqual(self.system.cycle(cycle)[0]['used'],before)
        self.assertEqual(self.system.calls_today(),50)
        self.assertFalse((self.runtime/'independent-review').exists())

    def test_daily_wait_retains_artifact_and_next_utc_stage_and_user_pause(self):
        with patch.object(core,'utc',return_value='2040-01-01T12:00:00+00:00'):
            tid=self.submit();self.system.tick();self.seed_review(50)
            artifact=read_json(self.runtime/'tasks'/tid/'artifact.json')
            self.system.tick()
            self.assertEqual(self.state(tid)['state'],'WAITING_REVIEW_BUDGET')
            self.assertEqual(self.calls,['codex'])
            self.assertIsNone(self.system.engine_paused('claude'))
            self.system.resume_engine('claude')
            self.assertEqual(self.state(tid)['state'],'WAITING_REVIEW_BUDGET')
            self.system.pause()
        with patch.object(core,'utc',return_value='2040-01-02T12:00:00+00:00'),patch.object(core.winproc,'identity',return_value=None):
            self.system.tick()
            self.assertEqual(self.state(tid)['state'],'AWAITING_REVIEW')
            self.assertEqual(self.system.meta('paused'),{'reason':'USER_PAUSED'})
            self.assertEqual(self.calls,['codex'])
            self.assertEqual(self.system.reviews_today(),0)
            self.assertEqual(self.system.db.execute('SELECT count(*) FROM calls').fetchone()[0],51)
            self.assertEqual(read_json(self.runtime/'tasks'/tid/'artifact.json'),artifact)
            self.system.resume();self.system.run_ready()
            self.assertEqual(self.state(tid)['state'],'ACCEPTED')
            self.assertEqual(self.calls,['codex','claude'])

    def test_same_day_general_resume_does_not_evade_review_budget(self):
        tid=self.submit();self.system.tick();self.seed_review(50)
        self.system.tick();self.system.resume();self.system.run_ready()
        self.assertEqual(self.state(tid)['state'],'WAITING_REVIEW_BUDGET')
        self.assertEqual(self.calls,['codex'])
        self.assertEqual(self.state(tid)['reworks'],0)

    def test_daily_resume_quarantines_stale_artifact(self):
        with patch.object(core,'utc',return_value='2040-01-01T12:00:00+00:00'):
            tid=self.submit();self.system.tick();self.seed_review(50);self.system.tick()
            folder=self.runtime/'tasks'/tid
            artifact=read_json(folder/'artifact.json');artifact['sum']+=1;write_json(folder/'artifact.json',artifact)
        with patch.object(core,'utc',return_value='2040-01-02T12:00:00+00:00'),patch.object(core.winproc,'identity',return_value=None):
            self.system.tick()
        self.assertEqual(self.state(tid)['state'],'NEEDS_ATTENTION')
        self.assertEqual(self.state(tid)['reason'],'STALE_WHILE_WAITING')
        self.assertEqual(self.calls,['codex'])

    def test_daily_resume_keeps_possibly_live_original_process_waiting(self):
        with patch.object(core,'utc',return_value='2040-01-01T12:00:00+00:00'):
            tid=self.submit();self.system.tick();self.seed_review(50);self.system.tick()
        with patch.object(core,'utc',return_value='2040-01-02T12:00:00+00:00'),patch.object(core.winproc,'identity',return_value='UNKNOWN'):
            self.system.tick()
        self.assertEqual(self.state(tid)['state'],'WAITING_REVIEW_BUDGET')
        self.assertEqual(self.calls,['codex'])

    def test_run_ready_rework_forwards_bound_feedback_then_finishes_without_polling(self):
        prompts=[];original=self.fake;reviews=[]
        def caller(*args,**kwargs):
            prompts.append((args[0],args[3]));return original(*args,**kwargs)
        def mutate(stage,value):
            if stage=='review':
                reviews.append(1)
                if len(reviews)==1:return {**value,'verdict':'REWORK','issues':['Explain the measured sign correctly.']}
            return value
        self.system.caller=caller;self.mutate=mutate
        tid=self.submit();self.system.run_ready(max_stages=6)
        self.assertEqual(self.state(tid)['state'],'ACCEPTED')
        self.assertEqual(self.state(tid)['reworks'],1)
        self.assertEqual(self.calls,['codex','claude','codex','claude'])
        self.assertIn('Explain the measured sign correctly.',prompts[2][1])
        self.assertIn('untrusted_review_data',prompts[2][1])
        self.assertNotIn('Explain the measured sign correctly.',prompts[0][1])
        self.system.run_ready();self.assertEqual(len(self.calls),4)
        self.assertEqual(self.system.db.execute('SELECT count(*) FROM tasks').fetchone()[0],1)

    def test_feedback_drops_forged_issue_not_matching_attempt_result(self):
        tid,spec=self.prepare_rework()
        self.assertIsNotNone(self.system.review_feedback(spec))
        folder=self.runtime/'tasks'/tid
        stored=read_json(folder/'review.json');stored['review']['issues']=['Injected unrecorded issue']
        write_json(folder/'review.json',stored)
        self.assertIsNone(self.system.review_feedback(spec))

    def test_feedback_drops_foreign_task_or_artifact_binding(self):
        tid,spec=self.prepare_rework();folder=self.runtime/'tasks'/tid
        stored=read_json(folder/'review.json');stored['review']['task_id']=str(uuid.uuid4())
        write_json(folder/'review.json',stored)
        self.assertIsNone(self.system.review_feedback(spec))

    def test_feedback_drops_changed_source(self):
        tid,spec=self.prepare_rework();self.revise(500)
        self.assertIsNone(self.system.review_feedback(spec))

    def test_automatic_pipeline_never_changes_task_id_to_escape_two_reworks(self):
        self.mutate=lambda stage,value: ({**value,'verdict':'REWORK','issues':['Still requires correction.']}
                                        if stage=='review' else value)
        tid=self.submit();self.system.run_ready(max_stages=6);self.system.run_ready()
        self.assertEqual(self.state(tid)['state'],'NEEDS_ATTENTION')
        self.assertEqual(self.state(tid)['reworks'],2)
        self.assertEqual(self.calls,['codex','claude']*3)
        self.assertEqual(self.system.db.execute('SELECT count(*) FROM tasks').fetchone()[0],1)

    def test_continuous_audit_four_keeps_original_legacy_counters_and_records(self):
        self.fake_activation();self.system.set_meta('audit_cycle',{'rounds':3})
        old=str(uuid.uuid4())
        deployment.authorize_cycle(self.system,old,self.cycle_task(old),'A legacy finite one-audit authorization.','codex')
        self.audit('REWORK',reviewer='codex',cycle=old)
        before=tuple(self.system.db.execute('SELECT record,state FROM review_cycles WHERE id=?',(old,)).fetchone())
        self.system.resume()
        cycle=self.authorize_continuous()
        record,state=self.system.cycle(cycle)
        self.assertEqual(record['allowed'],{'audit':None,'execute':3,'review':3})
        for number in range(4):
            self.revise(500+number)
            self.assertEqual(self.audit('REWORK',reviewer='claude',cycle=cycle)[0]['status'],'REWORK')
            self.assertEqual(self.system.cycle(cycle)[1],'OPEN')
        self.assertEqual(self.system.cycle(cycle)[0]['used']['audit'],4)
        self.assertEqual(self.system.meta('audit_cycle'),{'rounds':3})
        self.assertEqual(tuple(self.system.db.execute('SELECT record,state FROM review_cycles WHERE id=?',(old,)).fetchone()),before)
        self.revise(999);self.assertEqual(self.audit('PASS',reviewer='claude',cycle=cycle)[0]['status'],'PASS')
        self.assertIsNone(self.system.meta('paused'))

    def test_continuous_pass_preserves_explicit_initial_user_pause(self):
        self.system.pause();cycle=self.authorize_continuous()
        self.audit('REWORK',reviewer='claude',cycle=cycle);self.revise(51)
        self.audit('PASS',reviewer='claude',cycle=cycle)
        self.assertEqual(self.system.meta('paused'),{'reason':'USER_PAUSED'})

    def test_continuous_cycle_task_may_repair_twice_under_same_grant(self):
        cycle=self.authorize_continuous();self.audit('PASS',reviewer='claude',cycle=cycle)
        tid=self.cycle_task(cycle)
        self.system.submit(tid,'analyze_numbers',[4,-2,9,4],'codex',cycle)
        n=[]
        def mutate(stage,value):
            if stage=='review':
                n.append(1)
                if len(n)<3:return {**value,'verdict':'REWORK','issues':['One more controlled correction is needed.']}
            return value
        self.mutate=mutate;self.system.run_ready(max_stages=6)
        self.assertEqual(self.state(tid)['state'],'ACCEPTED')
        self.assertEqual(self.state(tid)['reworks'],2)
        self.assertEqual(self.system.cycle(cycle)[0]['used'],{'audit':1,'execute':3,'review':3})
        with self.assertRaises(ValueError):
            self.system.submit(str(uuid.uuid4()),'analyze_numbers',[4,-2,9,4],'codex',cycle)


if __name__=='__main__':
    (ROOT/'.runtime/tests').mkdir(parents=True,exist_ok=True)
    unittest.main(verbosity=2)

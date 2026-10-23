"""Actual failure boundaries of the bounded continuation and context controls."""
import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,MagicMock,patch
from tests import test_worker_service as fixture
from researchops.worker_context import packet
from researchops.worker_store import WorkerError


class ContextTests(unittest.TestCase):
    def test_shared_accounting_contention_pauses_before_reserving_call(self):
        from types import SimpleNamespace
        from researchops.worker_review import charge
        class Busy(Exception):pass
        lock=MagicMock();lock.__enter__.side_effect=Busy()
        core=SimpleNamespace(Busy=Busy,Lock=Mock(return_value=lock))
        with patch('researchops.worker_review.active',return_value=(None,core,None,{},{})),patch('researchops.worker_review.time.monotonic',side_effect=[0,4]),patch('researchops.worker_review.sqlite3.connect') as connect:
            with self.assertRaisesRegex(WorkerError,'SHARED_REVIEW_ACCOUNTING_BUSY_NO_CALL_RESERVED'):charge(Path('unused'),'claude','test','review')
        connect.assert_not_called()
    def test_owned_process_cap_is_bounded_before_creating_job(self):
        from researchops.winproc import _owned_job
        for limit in (0,33,True,'32'):
            with self.assertRaises(ValueError):_owned_job(8192,process_limit=limit)
    def test_single_turn_json_judgment_is_strictly_validated_locally(self):
        from researchops.adapters import validate_review_json,CallError
        schema={'properties':{'binding_sha256':{'const':'expected'},'verdict':{'enum':['PASS','REWORK']},'issues':{'maxItems':2,'items':{'maxLength':20}}}}
        validate_review_json({'binding_sha256':'expected','verdict':'PASS','issues':[]},schema)
        for value in ({'binding_sha256':'wrong','verdict':'PASS','issues':[]}, {'binding_sha256':'expected','verdict':'PASS','issues':['x'*21]}, {'binding_sha256':'expected','verdict':'PASS','issues':[],'extra':True}):
            with self.assertRaises(CallError):validate_review_json(value,schema)
    def test_source_review_newlines_do_not_duplicate_unchanged_code(self):
        from tools.deploy_execution import source_change
        value=source_change('x.py',b'a=1\r\nb=2\r\n',b'a=1\nb=3\n',True)
        self.assertIn('-b=2',value['diff']);self.assertIn('+b=3',value['diff'])
        self.assertNotIn('-a=1',value['diff']);self.assertEqual(value['line_endings']['before_crlf'],2)
        self.assertNotEqual(value['before_sha256'],value['after_sha256'])
    def snapshot(self,text='value=1\n'):
        digest=hashlib.sha256(text.encode()).hexdigest()
        return dict(files={'x.py':{'sha256':digest,'bytes':len(text.encode())}},contents={'x.py':text},sha256=digest)
    def test_complete_diff_and_unchanged_source_remain_bound(self):
        turn=dict(id='task',prompt='fix x',response='done')
        a,_=packet(turn,'source',self.snapshot())
        b,_=packet(turn,'source',self.snapshot('value=2\n'),{**a,'review':{'verdict':'REWORK','issues':['wrong value']}})
        self.assertIn('-value=1',b['changes'][0]['diff']);self.assertIn('+value=2',b['changes'][0]['diff'])
        self.assertNotEqual(a['binding_sha256'],b['binding_sha256'])
        self.assertEqual(b['previous_review']['verdict'],'REWORK')
    def test_user_removed_24k_packet_gate_without_truncating_request(self):
        request='x'*25000
        value,size=packet(dict(id='x',prompt=request,response=''), 'source', self.snapshot())
        self.assertEqual(value['request'],request)
        self.assertGreater(size,24576)
    def test_first_review_retains_complete_source_once_without_duplicate_addition_diff(self):
        source=''.join('value_'+str(i)+'=42\n' for i in range(900))
        value,size=packet(dict(id='x',prompt='Review this exact source',response='done'),'source',self.snapshot(source))
        self.assertEqual(value['workspace']['contents']['x.py'],source)
        self.assertLess(size,24576)
        self.assertEqual(value['changes'][0]['content_ref'],'workspace.contents')
        self.assertEqual(value['changes'][0]['after'],value['workspace']['files']['x.py'])
        self.assertNotIn('diff',value['changes'][0])
    def test_large_required_source_is_preserved_without_24k_gate(self):
        source='x'*25000
        value,size=packet(dict(id='x',prompt='Review complete source',response=''),'source',self.snapshot(source))
        self.assertEqual(value['workspace']['contents']['x.py'],source)
        self.assertGreater(size,24576)
    def test_rework_new_file_not_duplicated_and_old_findings_remain(self):
        turn=dict(id='x',prompt='fix',response='')
        old,_=packet(turn,'source',self.snapshot())
        after=self.snapshot();after['contents']['report.md']='report\n'*2000
        after['files']['report.md']={'sha256':hashlib.sha256(after['contents']['report.md'].encode()).hexdigest(),'bytes':len(after['contents']['report.md'].encode())}
        value,_=packet(turn,'source',after,{**old,'review':{'verdict':'REWORK','issues':['unresolved']}})
        change=next(c for c in value['changes'] if c['path']=='report.md')
        self.assertEqual(change['content_ref'],'workspace.contents');self.assertNotIn('diff',change)
        self.assertEqual(value['workspace']['contents']['report.md'],after['contents']['report.md'])
        self.assertEqual(value['previous_review']['issues'],['unresolved'])
    def test_repair_keeps_deleted_source_diff_unchanged_source_and_prior_findings(self):
        before=self.snapshot();before['files']['y.py']={'sha256':'unchanged'};before['contents']['y.py']='keep=1\n'
        original,_=packet(dict(id='x',prompt='fix',response=''),'source',before)
        after={'files':{'y.py':before['files']['y.py']},'contents':{'y.py':'keep=1\n'},'sha256':'new'}
        value,_=packet(dict(id='x',prompt='fix',response=''),'source',after,{**original,'review':{'verdict':'REWORK','issues':['Must check deletion']}})
        self.assertIn('-value=1',value['changes'][0]['diff'])
        self.assertEqual(value['workspace']['contents']['y.py'],'keep=1\n')
        self.assertEqual(value['previous_review']['issues'],['Must check deletion'])
    def test_sensitive_filename_refused_before_read(self):
        from researchops.worker_review import workspace_snapshot
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'.env').write_text('private')
            with self.assertRaisesRegex(WorkerError,'SENSITIVE_WORKSPACE_PATH'):workspace_snapshot(Path(d))


class AutoLoopTests(unittest.TestCase):
    setUp=fixture.WorkerServiceTests.setUp
    turn=fixture.WorkerServiceTests.turn
    begin=fixture.WorkerServiceTests.begin
    def test_analysis_cannot_resume_an_execution_session(self):
        import uuid
        prior=self.turn('full')
        with self.assertRaisesRegex(WorkerError,'FRESH_READ_ONLY_SESSION'):
            self.store.submit(dict(id=str(uuid.uuid4()),session=prior['session'],prompt='Analyze text',mode='approval',effort='high',skills=[],kind='analysis'))
    def test_analysis_starts_fresh_with_actual_readonly_policy(self):
        import uuid
        self.store.submit(dict(id=str(uuid.uuid4()),session=None,prompt='Analyze text',mode='approval',effort='high',skills=[],kind='analysis'))
        turn=self.service.next_turn()
        self.service.rpc.call.side_effect=[{'thread':{'id':'owned'},'model':turn['model'],'approvalPolicy':'untrusted','sandbox':{'type':'readOnly'}},{'turn':{'id':'native'}}]
        with patch('researchops.worker_service.charge',return_value='call'):self.service.begin(turn)
        self.assertEqual(self.service.rpc.call.call_args.args[1]['sandboxPolicy'],{'type':'readOnly'})
    def completed(self,turn):
        self.service.handle({'method':'turn/completed','params':{'threadId':'owned','turn':{'id':'native','status':'completed'}}})
    def test_reviewer_missing_context_pauses_without_queuing_a_repair(self):
        turn=self.turn();self.begin(turn)
        self.review.side_effect=WorkerError('REVIEW_NEEDS_CONTEXT')
        self.completed(turn)
        current=self.store.status()['turns'][0]
        self.assertEqual(current['state'],'PAUSED_REVIEW')
        self.assertEqual(current['reason'],'REVIEW_NEEDS_CONTEXT')
        self.assertEqual(current['reworks'],0);self.assertIsNone(self.service.next_turn())
    def test_real_review_adapter_receives_fixed_skills_and_preserves_needs_context(self):
        from researchops.worker_review import review_turn
        turn=self.turn();turn['response']='Need actual evidence'
        Path(turn['workspace']).mkdir(parents=True)
        (Path(turn['workspace'])/'example.py').write_text('value=42\n',encoding='utf-8')
        def invoke(engine,machine,policy,prompt,schema,*args,**kwargs):
            self.assertIn('necessary',prompt)
            self.assertIn('NEEDS_CONTEXT',prompt)
            self.assertIn('#',prompt)
            binding=json.loads(schema.read_text())['properties']['binding_sha256']['const']
            return {'binding_sha256':binding,'verdict':'NEEDS_CONTEXT','issues':['Missing required.py caller']},{'exit_code':0,'tools_disabled':True}
        with patch('researchops.worker_review.active',return_value=(None,None,None,{},{})),patch('researchops.worker_review.charge',return_value='call'),patch('researchops.worker_review.adapters.invoke',side_effect=invoke):
            with self.assertRaisesRegex(WorkerError,'REVIEW_NEEDS_CONTEXT'):
                review_turn(self.root,self.store,turn,'source')
        results=list((self.store.runtime/'turns'/turn['id']/'reviews').glob('*/result.json'))
        self.assertEqual(json.loads(results[0].read_text())['status'],'NEEDS_CONTEXT')
        self.assertFalse((self.store.runtime/'turns'/turn['id']/'review-context.json').exists())
    def test_existing_attempt_requires_reconciliation_without_model_charge(self):
        turn=self.turn()
        attempt=self.store.runtime/'turns'/turn['id']/'attempts'/'0'
        attempt.mkdir(parents=True)
        self.service.rpc.call.return_value={'thread':{'id':'owned'},'model':turn['model'],'approvalPolicy':'untrusted','sandbox':{'type':'workspaceWrite'}}
        with patch('researchops.worker_service.charge') as charged,self.assertRaisesRegex(WorkerError,'ATTEMPT_ALREADY_STARTED_NEEDS_RECONCILIATION'):
            self.service.begin(turn)
        charged.assert_not_called()
        self.assertFalse(any(c.args[0]=='turn/start' for c in self.service.rpc.call.call_args_list))
    def test_rework_is_persisted_and_requeued_with_findings(self):
        turn=self.turn();self.begin(turn)
        self.review.return_value={'verdict':'REWORK','issues':['Fix the sum'],'binding_sha256':'b'*64}
        self.completed(turn)
        pending=self.service.next_turn();self.assertEqual(pending['reworks'],1)
        repair=json.loads((self.store.runtime/'turns'/turn['id']/'repair-1.json').read_text())
        self.assertEqual(repair['issues'],['Fix the sum'])
        self.service.rpc.call.side_effect=None
        self.begin(pending)
        self.assertIn('Fix the sum',self.service.rpc.call.call_args.args[1]['input'][0]['text'])
    def test_rework_limit_preserves_failure(self):
        turn=self.turn();self.begin(turn);turn['reworks']=2
        self.store.update(turn['id'],reworks=2)
        self.review.return_value={'verdict':'REWORK','issues':['still wrong']};self.completed(turn)
        self.assertIsNone(self.service.next_turn());self.assertEqual(self.store.status()['turns'][0]['state'],'NEEDS_REWORK')


if __name__=='__main__':unittest.main()

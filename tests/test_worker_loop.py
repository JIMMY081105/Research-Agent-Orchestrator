"""Actual failure boundaries of the bounded continuation and context controls."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from tests import test_worker_service as fixture
from researchops.worker_context import packet
from researchops.worker_store import WorkerError


class ContextTests(unittest.TestCase):
    def snapshot(self,text='value=1\n'):
        return dict(files={'x.py':{'sha256':text}},contents={'x.py':text},sha256=text)
    def test_complete_diff_and_unchanged_source_remain_bound(self):
        turn=dict(id='task',prompt='fix x',response='done')
        a,_=packet(turn,'source',self.snapshot())
        b,_=packet(turn,'source',self.snapshot('value=2\n'),{**a,'review':{'verdict':'REWORK','issues':['wrong value']}})
        self.assertIn('-value=1',b['changes'][0]['diff']);self.assertIn('+value=2',b['changes'][0]['diff'])
        self.assertNotEqual(a['binding_sha256'],b['binding_sha256'])
        self.assertEqual(b['previous_review']['verdict'],'REWORK')
    def test_context_limit_fails_before_model_charge(self):
        with self.assertRaisesRegex(WorkerError,'CONTEXT_LIMIT'):
            packet(dict(id='x',prompt='x'*25000,response=''), 'source', self.snapshot())
    def test_sensitive_filename_refused_before_read(self):
        from researchops.worker_review import workspace_snapshot
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'.env').write_text('private')
            with self.assertRaisesRegex(WorkerError,'SENSITIVE_WORKSPACE_PATH'):workspace_snapshot(Path(d))


class AutoLoopTests(unittest.TestCase):
    setUp=fixture.WorkerServiceTests.setUp
    turn=fixture.WorkerServiceTests.turn
    begin=fixture.WorkerServiceTests.begin
    def completed(self,turn):
        self.service.handle({'method':'turn/completed','params':{'threadId':'owned','turn':{'id':'native','status':'completed'}}})
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

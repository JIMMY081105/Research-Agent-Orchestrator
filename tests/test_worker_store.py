"""Durability, exact permission/approval binding and rejected admissions."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch

from researchops.worker_store import Store, WorkerError, OWNER, policy, save, utc
from researchops import winproc


class WorkerStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root, initialize=True)
        save(self.root / 'worker/activation.json', {'owner': OWNER, 'sha256': 'a' * 64})
        self.service = {'owner': OWNER, 'pid': os.getpid(), 'birth': winproc.identity(os.getpid()),
            'source_sha256': 'a' * 64, 'observed_at': utc(), 'state': 'RUNNING', 'default_model': 'test',
            'skills': [{'id': 'known', 'name': 'test'}]}
        save(self.root / 'worker/service.json', self.service)
        self.request = {'id': str(uuid.uuid4()), 'session': None, 'prompt': 'Write a bounded test artifact.',
                        'mode': 'approval', 'effort': 'high', 'skills': []}

    def queued(self):
        self.store.submit(self.request)
        with self.store.db(True) as db:
            return dict(db.execute('SELECT * FROM turns').fetchone())

    def approval(self, method='item/commandExecution/requestApproval'):
        turn = self.queued(); turn.update(thread='owned', native_turn='native')
        self.store.update(turn['id'], state='RUNNING', native_turn='native')
        params = {'threadId': 'owned', 'turnId': 'native', 'command': 'write marker', 'cwd': str(self.root)}
        if 'requestUserInput' in method:
            params['questions'] = [{'id': 'choice', 'question': 'Which?'}]
        aid = self.store.approval(turn, {'id': 77, 'method': method, 'params': params})
        return turn, aid

    def test_permission_profiles_use_native_sandbox_and_real_approval_policy(self):
        self.assertEqual(policy('approval', 'C:/task'), {'approvalPolicy': 'untrusted',
            'sandboxPolicy': {'type': 'workspaceWrite', 'writableRoots': ['C:/task'], 'networkAccess': False}})
        self.assertEqual(policy('full', 'C:/task'), {'approvalPolicy': 'never', 'sandboxPolicy': {'type': 'dangerFullAccess'}})
        with self.assertRaises(WorkerError): policy('bypass', 'C:/task')

    def test_native_mode_speed_effort_validation_is_catalog_bound(self):
        self.service.update(models=['test'],work_modes=['task','plan','goal'],model_details={'test':{'efforts':['low','xhigh'],'service_tiers':['priority']}})
        save(self.root/'worker/service.json',self.service)
        request={**self.request,'work_mode':'goal','service_tier':'priority','goal_objective':'Exact objective','effort':'xhigh'}
        self.assertEqual(self.store.submit(request)['state'],'QUEUED')
        self.store.update(request['id'],state='REVIEW_PASS')
        for value in ({'service_tier':'ultrafast'},{'work_mode':'invented'},{'effort':'high'},{'goal_objective':''},{'goal_objective':'x'*4001},{'goal_objective':'sk-'+'x'*30}):
            with self.subTest(value=value),self.assertRaises(WorkerError):self.store.submit({**request,'id':str(uuid.uuid4()),**value})

    def test_duplicate_restart_is_one_turn_and_mode_is_immutable(self):
        first = self.store.submit(self.request)
        fresh = Store(self.root)
        self.assertTrue(fresh.submit(self.request)['duplicate'])
        with self.assertRaisesRegex(WorkerError, 'INPUT_CONFLICT'):
            fresh.submit({**self.request, 'mode': 'full'})
        with self.store.db(True) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM turns').fetchone()[0], 1)
        saved = json.loads((self.root / 'worker/turns' / first['id'] / 'request.json').read_text())
        self.assertEqual(saved, self.request)

    def test_only_one_writer_and_no_foreign_session_adoption(self):
        turn = self.queued()
        with self.assertRaisesRegex(WorkerError, 'BUSY'):
            self.store.submit({**self.request, 'id': str(uuid.uuid4())})
        self.store.update(turn['id'], state='REVIEW_PASS')
        with self.assertRaisesRegex(WorkerError, 'UNKNOWN_WORKER_SESSION'):
            self.store.submit({**self.request, 'id': str(uuid.uuid4()), 'session': str(uuid.uuid4())})

    def test_malformed_or_command_admissions_are_rejected(self):
        changes = [{'id': '../escape'}, {'prompt': ''}, {'prompt': 'x' * 20001}, {'mode': []},
                   {'skills': [{}]}, {'skills': ['unknown']}, {'cwd': 'C:/'}, {'effort': 'ultra'},
                   {'prompt': 'sk-' + 'x' * 30}, {'skills': ['known', 'known']}]
        for change in changes:
            with self.subTest(change=list(change)), self.assertRaises(WorkerError):
                self.store.submit({**self.request, **change})
        self.assertEqual(self.store.status()['turns'], [])

    def test_stale_service_wrong_pid_or_activation_fails_closed(self):
        for change in ({'birth': 'invalid'}, {'source_sha256': 'b' * 64}, {'observed_at': '2000-01-01T00:00:00+00:00'}, {'state': 'PAUSED'}):
            save(self.root / 'worker/service.json', {**self.service, **change})
            self.assertFalse(self.store.capability()['enabled'])
            with self.assertRaisesRegex(WorkerError, 'UNAVAILABLE'): self.store.submit(self.request)

    def test_approval_scoped_to_exact_native_turn_and_denial_is_durable(self):
        turn, aid = self.approval()
        bad = {'id': aid, 'turn': str(uuid.uuid4()), 'decision': 'accept'}
        with self.assertRaisesRegex(WorkerError, 'STALE'): self.store.decide(bad)
        request = {'id': aid, 'turn': turn['id'], 'decision': 'decline'}
        self.assertFalse(self.store.decide(request)['duplicate'])
        self.assertTrue(self.store.decide(request)['duplicate'])
        with self.assertRaisesRegex(WorkerError, 'ALREADY_ANSWERED'):
            self.store.decide({**request, 'decision': 'accept'})
        self.store.update(turn['id'], state='REVIEW_PASS')
        with self.assertRaisesRegex(WorkerError, 'STALE'): self.store.decide(request)

    def test_wrong_native_binding_cannot_create_approval(self):
        turn = self.queued(); turn.update(thread='owned', native_turn='native')
        with self.assertRaisesRegex(WorkerError, 'BINDING'):
            self.store.approval(turn, {'id': 5, 'method': 'item/fileChange/requestApproval',
                'params': {'threadId': 'foreign', 'turnId': 'native'}})
        self.assertEqual(self.store.status()['approvals'], [])

    def test_user_input_requires_exact_questions_and_retries_are_idempotent(self):
        turn, aid = self.approval('item/tool/requestUserInput')
        base = {'id': aid, 'turn': turn['id'], 'decision': 'answer'}
        with self.assertRaises(WorkerError): self.store.decide({**base, 'answers': {'other': 'text'}})
        req = {**base, 'answers': {'choice': 'A'}}
        self.assertFalse(self.store.decide(req)['duplicate'])
        self.assertTrue(self.store.decide(req)['duplicate'])
        with self.store.db(True) as db:
            answer = json.loads(db.execute('SELECT decision FROM approvals').fetchone()[0])
        self.assertEqual(answer, {'answers': {'choice': {'answers': ['A']}}})

    def test_queued_cancel_does_not_spawn_and_get_never_dispatches(self):
        turn = self.queued()
        self.store.cancel({'id': turn['id']})
        self.assertEqual(Store(self.root).status()['turns'][0]['state'], 'CANCELLED')
        with self.assertRaisesRegex(WorkerError, 'ACTIVE'): self.store.cancel({'id': str(uuid.uuid4())})
        with self.assertRaisesRegex(WorkerError, 'EVENT_NOT_ALLOWED'):
            self.store.event(turn['session'], turn['id'], 'reasoning', 'hidden')

    def test_pause_blocks_new_admission_without_erasing_existing_turn(self):
        turn = self.queued()
        save(self.root / 'worker/admission-paused.json', {'owner': OWNER})
        self.assertFalse(self.store.capability()['enabled'])
        with self.assertRaisesRegex(WorkerError, 'UNAVAILABLE'):
            self.store.submit({**self.request, 'id': str(uuid.uuid4())})
        self.assertEqual(self.store.status()['turns'][0]['id'], turn['id'])

    def test_windows_reader_sharing_conflict_retries_atomic_save_without_partial_json(self):
        path = self.root / 'status.json'; save(path, {'state': 'old'})
        ready = threading.Event()
        def hold():
            with path.open('rb') as reader:
                ready.set(); time.sleep(.12)
                self.assertEqual(json.load(reader), {'state': 'old'})
        thread = threading.Thread(target=hold); thread.start(); self.assertTrue(ready.wait(2))
        try: save(path, {'state': 'new'})
        finally: thread.join(2)
        self.assertEqual(json.loads(path.read_text()), {'state': 'new'})

    def test_persistent_sharing_denial_is_bounded_and_keeps_previous_complete_record(self):
        path = self.root / 'status.json'; save(path, {'state': 'old'})
        started = time.monotonic()
        with path.open('rb'), self.assertRaises(PermissionError): save(path, {'state': 'new'})
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(json.loads(path.read_text()), {'state': 'old'})


if __name__ == '__main__': unittest.main()

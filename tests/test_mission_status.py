"""Public progress must retain real identities, reject unsupported verdicts and remain read-only."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from researchops.mission_status import phase_for, review_summary, workflow
from researchops.worker_store import Store


class MissionStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.turn = str(uuid.uuid4())
        self.review = str(uuid.uuid4())
        self.path = self.root / 'turns' / self.turn / 'reviews' / self.review / 'result.json'
        self.path.parent.mkdir(parents=True)

    def write_review(self, **changes):
        value = {'status': 'PASS', 'binding_sha256': 'a' * 64,
                 'review': {'verdict': 'PASS', 'binding_sha256': 'a' * 64, 'issues': []},
                 'evidence': {'tools_disabled': True, 'exit_code': 0},
                 'created_at': '2026-10-20T20:00:00Z', 'scope': 'OWNED_WORKSPACE',
                 'settings': {'model': None, 'effort': 'high',
                              'permission_mode': 'dontAsk', 'tools_disabled': True}}
        value.update(changes)
        self.path.write_text(json.dumps(value), encoding='utf-8')
        return value

    def test_actual_settings_and_no_invented_model_or_master_plan(self):
        self.write_review()
        row = review_summary(self.root, self.turn)
        self.assertEqual(row['status'], 'PASS')
        self.assertIsNone(row['model'])
        self.assertEqual((row['effort'], row['permission_mode']), ('high', 'dontAsk'))
        turns = [{'id': self.turn, 'session': 'session', 'state': 'REVIEW_PASS',
                  'created': 'created', 'updated': 'updated', 'mode': 'approval', 'effort': 'xhigh'}]
        result = workflow(self.root, turns, [{'id': 'session', 'model': 'reported-model'}], [], 1)
        self.assertIsNone(result['master_plan'])
        self.assertFalse(result['reasoning_available'])
        self.assertEqual(result['stages'][0]['model'], 'reported-model')
        self.assertEqual(result['stages'][0]['permission_mode'], 'approval')

    def test_old_reviews_without_settings_stay_unknown(self):
        self.write_review(settings={})
        row = review_summary(self.root, self.turn)
        self.assertIsNone(row['model'])
        self.assertIsNone(row['effort'])
        self.assertIsNone(row['permission_mode'])
        self.assertFalse(row['tools_disabled'])

    def test_exit_zero_or_model_claim_alone_is_not_a_verified_verdict(self):
        for change in ({'evidence': {'exit_code': 0}},
                       {'evidence': {'exit_code': False, 'tools_disabled': True}},
                       {'review': {'verdict': 'PASS', 'binding_sha256': 'b' * 64}},
                       {'review': {'verdict': 'REWORK', 'binding_sha256': 'a' * 64}},
                       {'review': {'verdict': 'PASS', 'binding_sha256': 'a' * 64, 'issues': ['unresolved']}},
                       {'binding_sha256': 'not-a-binding'}):
            with self.subTest(change=change):
                self.write_review(**change)
                self.assertEqual(review_summary(self.root, self.turn)['status'], 'UNVERIFIED')

    def test_rework_returns_bounded_public_issues_not_packages(self):
        value = self.write_review(status='REWORK', review={'verdict': 'REWORK',
            'binding_sha256': 'a' * 64, 'issues': ['fix geometry', 'x' * 3000]})
        value['private_reasoning'] = 'NEVER_EXPOSE_THIS'
        value['package'] = {'prompt': 'NEVER_READ_PACKAGE'}
        self.path.write_text(json.dumps(value), encoding='utf-8')
        row = review_summary(self.root, self.turn)
        self.assertEqual(row['status'], 'REWORK')
        self.assertEqual(len(row['issues'][1]), 1500)
        self.assertNotIn('NEVER_', json.dumps(row))

    def test_missing_invalid_and_oversized_records_are_unknown(self):
        self.assertIsNone(review_summary(self.root, '../foreign'))
        self.assertIsNone(review_summary(self.root, self.turn))
        self.path.write_text('not json', encoding='utf-8')
        self.assertIsNone(review_summary(self.root, self.turn))
        self.path.write_bytes(b' ' * (128 * 1024 + 1))
        self.assertIsNone(review_summary(self.root, self.turn))

    def test_unrecognized_folder_does_not_hide_real_review(self):
        self.write_review()
        (self.path.parent.parent / 'not-an-audit').mkdir()
        self.assertEqual(review_summary(self.root, self.turn)['status'], 'PASS')

    def test_status_reads_do_not_dispatch_create_or_rewrite(self):
        store = Store(self.root, initialize=True)
        stamp = '2026-10-20T20:00:00Z'
        session = str(uuid.uuid4())
        with store.db() as db:
            db.execute('INSERT INTO sessions(id,workspace,model,created) VALUES(?,?,?,?)',
                       (session, 'workspace', 'actual-model', stamp))
            db.execute('INSERT INTO turns(id,session,input_hash,prompt,mode,effort,skills,state,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (self.turn, session, 'hash', 'visible user question', 'full', 'high', '[]', 'REVIEW_PASS', stamp, stamp))
        before = hashlib.sha256(store.db_path.read_bytes()).hexdigest()
        value = store.status()
        self.assertEqual(value['turns'][0]['prompt'], 'visible user question')
        self.assertEqual(value['workflow']['total_turns'], 1)
        self.assertEqual(value['workflow']['stages'][0]['model'], 'actual-model')
        self.assertEqual(hashlib.sha256(store.db_path.read_bytes()).hexdigest(), before)

    def test_phases_do_not_infer_stall_from_elapsed_time(self):
        self.assertEqual(phase_for('RUNNING'), 'execute')
        self.assertEqual(phase_for('WAITING_APPROVAL'), 'execute')
        self.assertEqual(phase_for('PAUSED_REVIEW'), 'review')
        self.assertEqual(phase_for('REVIEW_PASS'), 'result')
        self.assertEqual(phase_for('NEEDS_REWORK'), 'result')
        self.assertEqual(phase_for('PAUSED_CONNECTION'), 'execute')
        self.assertEqual(phase_for('STALLED'), 'execute')
        self.assertIsNone(phase_for('UNREPORTED_NEW_STATE'))


if __name__ == '__main__':
    unittest.main()

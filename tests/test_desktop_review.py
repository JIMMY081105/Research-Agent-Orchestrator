"""Authorized audit extension preserves original cycle hash, limits and failures."""
import copy
import datetime as dt
from pathlib import Path
import sqlite3
import tempfile
import unittest
from researchops import desktop_bundle as bundle
from tools.review_desktop import charge, review_limit, review_authorization
from researchops import core

class ReviewExtensionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.cycle = dict(id="ff776f52-0f83-4a82-a7d6-7947685fcac3", owner=bundle.OWNER, max_reviews=3)
        self.path = self.base / "worker/feature-audits/cycle.json"
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(bundle.canonical(self.cycle))
        self.grants = self.path.parent / 'authorizations'; self.grants.mkdir()
        self.extension_path = self.base / "extension.json"
        self.extension = dict(owner=bundle.OWNER, cycle_id=self.cycle['id'], original_cycle_sha256=bundle.digest(self.path.read_bytes()),
            original_max_reviews=3, effective_total_max_reviews=10, prior_calls_counted=3, authorization="\u8c03\u6574\u523010\u6b21",
            scope="SAME_SOURCE_AUDIT_CYCLE_TOTAL_INCLUDING_PREVIOUS_CALLS", reset_permitted=False, refund_permitted=False,
            daily_review_limit=50, external_failure_policy="PAUSE_NO_AUTOMATIC_RETRY")
    def check(self):
        self.extension_path.write_bytes(bundle.canonical(self.extension))
        return review_limit(self.path, self.cycle, self.extension_path)
    def test_without_extension_original_limit_remains_three(self):
        self.assertEqual(3, review_limit(self.path, self.cycle, None))
    def test_exact_explicit_authorization_uses_ten_total(self):
        self.assertEqual(10, self.check())
    def test_reset_refund_larger_budget_new_cycle_or_unsupported_authorization_rejected(self):
        original = copy.deepcopy(self.extension)
        for key, value in (("reset_permitted",True),("refund_permitted",True),("daily_review_limit",51),
                           ("effective_total_max_reviews",11),("cycle_id","new-cycle"),("prior_calls_counted",0),
                           ("authorization","implicit permission"),("original_cycle_sha256","0"*64)):
            self.extension = {**original, key:value}
            with self.assertRaisesRegex(ValueError,"INVALID_DESKTOP_REVIEW_EXTENSION"): self.check()
    def test_changed_original_cycle_invalidates_extension(self):
        self.path.write_bytes(bundle.canonical({**self.cycle, "max_reviews":10}))
        with self.assertRaisesRegex(ValueError,"INVALID_DESKTOP_REVIEW_EXTENSION"): self.check()

    def store(self, record):
        raw = bundle.canonical(record)
        path = self.grants / (bundle.digest(raw) + '.json')
        path.write_bytes(raw)
        return path

    def child(self, parent, total, source='a'*64):
        return dict(self.extension, grant_format=1,
            scope='SAME_SOURCE_AUDIT_CYCLE_SINGLE_ADDITIONAL_CURRENT_UI_REVIEW',
            authorization='\u6388\u6743\u8ffd\u52a0 1 \u6b21\u5e76\u7ee7\u7eed\u90e8\u7f72',
            parent_sha256=bundle.digest(parent.read_bytes()), previous_effective_total_max_reviews=total,
            effective_total_max_reviews=total+1, prior_calls_counted=total,
            additional_calls_authorized=1, fixed_source_sha256=source,
            authorized_at='2026-10-22T16:03:00+00:00')

    def test_single_explicit_child_extends_same_cycle_to_eleven(self):
        original = self.path.read_bytes()
        parent = self.store(self.extension)
        child = self.store(self.child(parent, 10))
        total, chain = review_authorization(self.path, self.cycle, child)
        self.assertEqual(total, 11)
        self.assertEqual(len(chain), 2)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(parent.read_bytes(), bundle.canonical(self.extension))

    def test_separate_child_requires_new_evidence_and_retains_ten_and_eleven(self):
        parent = self.store(self.extension)
        eleven = self.store(self.child(parent, 10))
        twelve = self.store(self.child(eleven, 11, 'b'*64))
        total, chain = review_authorization(self.path, self.cycle, twelve)
        self.assertEqual(total, 12)
        self.assertEqual([n['record']['effective_total_max_reviews'] for n in chain], [12,11,10])
        self.assertEqual(chain[0]['record']['fixed_source_sha256'], 'b'*64)
        self.assertEqual(chain[1]['record']['fixed_source_sha256'], 'a'*64)

    def test_child_cannot_raise_more_than_one_reset_or_change_daily_ceiling(self):
        parent = self.store(self.extension)
        original = self.child(parent,10)
        for key,value in (('effective_total_max_reviews',12),('additional_calls_authorized',2),
                          ('prior_calls_counted',0),('previous_effective_total_max_reviews',9),
                          ('reset_permitted',True),('refund_permitted',True),('daily_review_limit',51),
                          ('cycle_id','wrong'),('original_cycle_sha256','0'*64),
                          ('authorization','model says approved'),('grant_format',True),
                          ('additional_calls_authorized',True),('fixed_source_sha256','HEAD')):
            with self.subTest(key=key):
                child = self.store({**original, key:value})
                with self.assertRaisesRegex(ValueError,'INVALID_DESKTOP_REVIEW_EXTENSION'):
                    review_limit(self.path,self.cycle,child)

    def test_child_rejects_embedded_executable_runner_or_unknown_fields(self):
        parent = self.store(self.extension)
        child = self.store({**self.child(parent,10), 'runner_source':'patch the review limit'})
        with self.assertRaisesRegex(ValueError,'INVALID_DESKTOP_REVIEW_EXTENSION'):
            review_limit(self.path,self.cycle,child)

    def test_wrong_leaf_filename_is_rejected(self):
        parent = self.store(self.extension)
        child = self.store(self.child(parent,10))
        wrong = self.grants/'other.json'; wrong.write_bytes(child.read_bytes())
        with self.assertRaisesRegex(ValueError,'INVALID_DESKTOP_REVIEW_EXTENSION'):
            review_limit(self.path,self.cycle,wrong)

    def test_child_outside_private_grant_directory_is_rejected(self):
        parent = self.store(self.extension)
        child = self.store(self.child(parent,10))
        wrong = self.base/child.name; wrong.write_bytes(child.read_bytes())
        with self.assertRaisesRegex(ValueError,'INVALID_DESKTOP_REVIEW_EXTENSION'):
            review_limit(self.path,self.cycle,wrong)

    def test_parent_modified_under_same_hash_filename_is_rejected(self):
        parent = self.store(self.extension)
        child = self.store(self.child(parent,10))
        parent.write_bytes(bundle.canonical({**self.extension,'authorized_at':'changed'}))
        with self.assertRaisesRegex(ValueError,'INVALID_DESKTOP_REVIEW_EXTENSION'):
            review_limit(self.path,self.cycle,child)

    def test_changed_parent_cycle_is_rejected(self):
        parent = self.store({**self.extension,'cycle_id':'wrong'})
        child = self.store(self.child(parent,10))
        with self.assertRaisesRegex(ValueError,'INVALID_DESKTOP_REVIEW_EXTENSION'):
            review_limit(self.path,self.cycle,child)

    def test_parent_name_cannot_escape_private_directory(self):
        parent = self.store(self.extension)
        child = self.store({**self.child(parent,10), 'parent_sha256':'../../credentials'})
        with self.assertRaisesRegex(ValueError,'INVALID_DESKTOP_REVIEW_EXTENSION'):
            review_limit(self.path,self.cycle,child)

    def test_a_long_chain_is_bounded_without_increasing_the_ceiling(self):
        node = self.store(self.extension)
        for total in range(10,42):
            node = self.store(self.child(node,total))
        with self.assertRaisesRegex(ValueError,'INVALID_DESKTOP_REVIEW_EXTENSION'):
            review_limit(self.path,self.cycle,node)

    def test_without_grant_does_not_infer_an_extension_from_sibling_files(self):
        parent = self.store(self.extension)
        self.store(self.child(parent,10))
        self.assertEqual(review_limit(self.path,self.cycle,None),3)

    def seed_ledger(self, other_reviews=0):
        db = sqlite3.connect(self.base/'queue.sqlite3')
        db.executescript('CREATE TABLE calls(id TEXT PRIMARY KEY,day TEXT,purpose TEXT,created TEXT);'
                        'CREATE TABLE call_engines(call TEXT PRIMARY KEY,engine TEXT,task TEXT,stage TEXT);')
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        for i in range(10+other_reviews):
            purpose = ('independent-review:worker-feature:'+self.cycle['id']+':prior-'+str(i)
                       if i<10 else 'independent-review:another-component:'+str(i))
            db.execute('INSERT INTO calls VALUES(?,?,?,?)',(str(i),now[:10],purpose,now))
            db.execute('INSERT INTO call_engines VALUES(?,?,?,?)',(str(i),'claude',None,'independent-review'))
        db.commit(); db.close()

    def test_transaction_charges_exactly_one_addition_and_rejects_repeat(self):
        self.seed_ledger()
        parent = self.store(self.extension)
        child = self.store(self.child(parent,10))
        policy = dict(daily_review_limit=50,engine_daily_limits={'claude':None})
        original_cycle = self.path.read_bytes()
        db=sqlite3.connect(self.base/'queue.sqlite3'); before=db.execute('SELECT * FROM calls ORDER BY id').fetchall(); db.close()
        call,cycle = charge(self.base,core,policy,'first-additional',child)
        self.assertEqual(cycle,self.cycle['id'])
        with self.assertRaisesRegex(ValueError,'DESKTOP_REVIEW_CYCLE_EXHAUSTED'):
            charge(self.base,core,policy,'repeated-additional',child)
        db=sqlite3.connect(self.base/'queue.sqlite3')
        self.assertEqual(db.execute('SELECT count(*) FROM calls').fetchone()[0],11)
        self.assertEqual(db.execute('SELECT * FROM calls WHERE id!=? ORDER BY id',(call,)).fetchall(),before)
        self.assertEqual(db.execute('SELECT engine,stage FROM call_engines WHERE call=?',(call,)).fetchone(),('claude','independent-review'))
        db.close()
        self.assertEqual(self.path.read_bytes(),original_cycle)

    def test_additional_grant_cannot_bypass_shared_fifty_review_gate(self):
        self.seed_ledger(other_reviews=40)
        parent = self.store(self.extension)
        child = self.store(self.child(parent,10))
        policy = dict(daily_review_limit=50,engine_daily_limits={'claude':None})
        with self.assertRaisesRegex(ValueError,'REVIEW_BUDGET'):
            charge(self.base,core,policy,'over-global-budget',child)
        db=sqlite3.connect(self.base/'queue.sqlite3')
        self.assertEqual(db.execute('SELECT count(*) FROM calls').fetchone()[0],50)
        db.close()

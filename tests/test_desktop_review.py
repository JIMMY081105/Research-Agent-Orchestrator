"""Authorized audit extension preserves original cycle hash, limits and failures."""
import copy
from pathlib import Path
import tempfile
import unittest
from researchops import desktop_bundle as bundle
from tools.review_desktop import review_limit

class ReviewExtensionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.cycle = dict(id="ff776f52-0f83-4a82-a7d6-7947685fcac3", owner=bundle.OWNER, max_reviews=3)
        self.path = self.base / "cycle.json"; self.path.write_bytes(bundle.canonical(self.cycle))
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

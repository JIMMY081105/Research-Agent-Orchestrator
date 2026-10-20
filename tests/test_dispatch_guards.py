"""Small regression tests for drain concurrency, inherited deadlines and feedback binding.

Copy to tests/test_dispatch_guards.py. Uses an isolated temporary queue and fake model data;
it starts no model, scene tool, remote job or scheduler.
"""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent/"researchops/core.py").exists())
sys.path.insert(0, str(ROOT))
from researchops import core
from researchops.core import System
from researchops.integrity import read_json, write_json


class DispatchGuards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bgv-dispatch-guard-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source, self.runtime = self.base/"source", self.base/"runtime"
        for name in ("config", "prompts", "skills"):
            shutil.copytree(ROOT/name, self.source/name)
        self.calls, self.prompts, self.timeouts = [], [], []
        self.reject_once = False
        self.system = System(self.source, self.runtime, self.fake)
        self.addCleanup(self.system.close)

    def fake(self, engine, machine, policy, prompt, schema, cwd, on_start, session):
        self.calls.append(engine); self.prompts.append(prompt); self.timeouts.append(policy["timeout_seconds"])
        # Unit fixture identity is deliberately not a live process identity.
        on_start(os.getpid(), "1")
        spec = read_json(Path(cwd).parent/"spec.json")
        if engine == "codex":
            value = self.system.artifact_expected(spec)
        else:
            artifact = read_json(Path(cwd).parent/"artifact.json")
            reject = self.reject_once
            self.reject_once = False
            value = {"task_id": spec["id"], "binding_sha256": self.system.binding(spec, artifact),
                     "verdict": "REWORK" if reject else "PASS", "issues": ["check fixed sums"] if reject else []}
        return value, {"engine": engine, "exit_code": 0, "requested_session_id": session,
                       "session_id": session, "tools_disabled": True}

    def submit(self):
        return self.system.submit(str(uuid.uuid4()), "analyze_numbers", [1, 2, 3])

    def state(self, tid):
        return self.system.db.execute("SELECT state FROM tasks WHERE id=?", (tid,)).fetchone()[0]

    def reworked(self):
        tid = self.submit()
        self.reject_once = True
        self.system.tick(); self.system.tick()
        self.assertEqual(self.state(tid), "REWORK")
        return tid, read_json(self.runtime/"tasks"/tid/"spec.json")

    def test_busy_drain_does_not_write_reports_outside_the_lock(self):
        with patch.object(self.system, "tick", return_value={"skipped": "INSTANCE_ALREADY_RUNNING"}), \
                patch.object(self.system, "report", return_value={}) as report:
            self.system.run_ready()
        report.assert_called_once_with(persist=False)
        self.assertEqual(self.calls, [])

    def test_drain_executes_codex_review_repair_and_revalidation(self):
        tid = self.submit()
        self.reject_once = True
        report = self.system.run_ready()
        self.assertEqual(self.state(tid), "ACCEPTED")
        self.assertEqual(self.calls, ["codex", "claude", "codex", "claude"])
        data = json.loads(self.prompts[2].split("TASK DATA\n", 1)[1])
        self.assertTrue(data["review_feedback"]["untrusted_review_data"])
        self.assertEqual(data["review_feedback"]["issues"], ["check fixed sums"])
        self.assertLessEqual(report["stages_checked"], 6)

    def test_nested_deadline_is_kept_and_restored(self):
        earlier = time.monotonic() + 30
        self.system._run_deadline = earlier
        seen = []
        with patch.object(self.system, "tick", side_effect=lambda *_: seen.append(self.system._run_deadline) or {"skipped": "fixture"}):
            self.system.run_ready(max_seconds=60)
        self.assertEqual(seen, [earlier])
        self.assertEqual(self.system._run_deadline, earlier)

    def test_cli_timeout_uses_remaining_drain_budget(self):
        tid = self.submit()
        self.system._run_deadline = time.monotonic() + 9
        self.system.tick()
        self.assertEqual(self.state(tid), "AWAITING_REVIEW")
        self.assertEqual(self.calls, ["codex"])
        self.assertTrue(1 <= self.timeouts[0] <= 9)
        self.assertEqual(self.system.policy["timeout_seconds"], read_json(self.source/"config/policy.json")["timeout_seconds"])

    def test_review_feedback_rejects_path_before_attempt_read(self):
        tid, spec = self.reworked()
        folder = self.runtime/"tasks"/tid
        stored = read_json(folder/"review.json")
        stored["call_id"] = "../../../do-not-read"
        write_json(folder/"review.json", stored)
        real, accessed = core.read_json, []
        def read(path):
            accessed.append(Path(path))
            if "do-not-read" in str(path):
                raise AssertionError("Untrusted call ID reached the filesystem")
            return real(path)
        with patch.object(core, "read_json", read):
            self.assertIsNone(self.system.review_feedback(spec))
        self.assertEqual(len(accessed), 2)

    def test_review_feedback_rejects_database_evidence_mismatch(self):
        tid, spec = self.reworked()
        self.assertIsNotNone(self.system.review_feedback(spec))
        call = read_json(self.runtime/"tasks"/tid/"review.json")["call_id"]
        self.system.db.execute("UPDATE attempts SET result=? WHERE id=?", ('{}', call))
        self.system.db.commit()
        self.assertIsNone(self.system.review_feedback(spec))

    def test_review_feedback_rejects_changed_source(self):
        tid, spec = self.reworked()
        (self.source/"changed.py").write_text("changed = True\n")
        self.assertIsNone(self.system.review_feedback(spec))


if __name__ == "__main__":
    unittest.main(verbosity=2)

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

from researchops import adapters, scene, winproc
from researchops.core import System, Lock, Busy, expected, utc
from researchops import deployment
from researchops.deployment import review_package, verify_activation
from researchops.integrity import canonical, digest, manifest, read_json, write_json

ROOT = Path(__file__).resolve().parents[1]


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT/".runtime"/"tests")
        self.base = Path(self.temp.name)
        self.source = self.base/"source"
        shutil.copytree(ROOT/"config", self.source/"config")
        shutil.copytree(ROOT/"prompts", self.source/"prompts")
        shutil.copytree(ROOT/"skills", self.source/"skills")
        (self.source/"researchops").mkdir()
        shutil.copyfile(ROOT/"researchops/scene_runner.py", self.source/"researchops/scene_runner.py")
        (self.source/"code.py").write_text("version = 1\n", encoding="utf-8")
        self.runtime = self.base/"runtime"
        self.calls = []
        self.bad = False
        self.call_failure = None
        self.on_review = None
        self.mutate = None
        self.engine_failure = {}
        self.scene_choice = None
        finished = subprocess.Popen([sys.executable, "-c", "pass"], creationflags=0x08000000)
        finished.wait()
        self.dead_child = finished.pid  # identity "1" never matches a live process
        self.system = System(self.source, self.runtime, self.fake)

    def tearDown(self):
        self.system.close()
        self.temp.cleanup()

    def fake(self, engine, machine, policy, prompt, schema, cwd, on_start, session):
        self.calls.append(engine)
        on_start(self.dead_child, "1")
        if self.call_failure:
            raise adapters.CallError(self.call_failure)
        if engine in self.engine_failure:
            on_start(self.dead_child, "1")  # the CLI started, then the service refused
            raise adapters.CallError(self.engine_failure[engine])
        tid = Path(cwd).parent.name
        spec = read_json(self.runtime/"tasks"/tid/"spec.json")
        if "fitting_templates" in prompt:
            data = json.loads(prompt.split("TASK DATA\n", 1)[1])
            value = {k: data[k] for k in ("task_id", "input_sha256", "source_sha256")}
            value.update(template=self.scene_choice or data["fitting_templates"][0],
                         rationale=["chosen from the supplied fitting templates and their margins"])
        elif "TASK DATA" in prompt:
            value = self.system.artifact_expected(spec)
            if spec["action"] == "analyze_text":
                value.pop("semantic_review")
                value["summary"] = "The supplied notes report the measured result."
                value["citations"] = [{"quote": spec["input"]["text"], "start": 0, "end": len(spec["input"]["text"])}]
            if self.bad:
                value["sum"] = 99999
        else:
            artifact = read_json(self.runtime/"tasks"/tid/"artifact.json")
            value = {"task_id": tid, "binding_sha256": self.system.binding(spec, artifact), "verdict": "PASS", "issues": []}
            if self.on_review:
                self.on_review()
        if self.mutate:
            value = self.mutate("execute" if "TASK DATA" in prompt else "review", value)
        # Same metadata contract as adapters.invoke (requested and actual session IDs).
        return value, {"engine": engine, "exit_code": 0, "requested_session_id": session, "session_id": session,
                       "tools_disabled": True}

    def limit(self, **limits):
        """An explicit local per-engine daily cap in this isolated source's policy."""
        path = self.source/"config/policy.json"
        policy = read_json(path)
        policy["engine_daily_limits"].update(limits)
        write_json(path, policy)
        self.system.close()
        self.system = System(self.source, self.runtime, self.fake)

    def submit(self, task=None, writer="codex"):
        tid = task or str(uuid.uuid4())
        self.system.submit(tid, "analyze_numbers", [4, -2, 9, 4], writer)
        return tid

    def state(self, task):
        return self.system.db.execute("SELECT * FROM tasks WHERE id=?", (task,)).fetchone()

    def test_normal_two_cli_and_exact_artifact(self):
        tid = self.submit()
        self.system.tick()
        self.assertEqual(self.state(tid)["state"], "AWAITING_REVIEW")
        self.system.tick()
        self.assertEqual(self.state(tid)["state"], "ACCEPTED")
        self.assertEqual(self.calls, ["codex", "claude"])
        self.assertTrue((self.runtime/"tasks"/tid/"acceptance.json").exists())

    def test_reverse_writer_reviewer(self):
        tid = self.submit(writer="claude")
        self.system.tick(); self.system.tick()
        self.assertEqual(self.calls, ["claude", "codex"])
        self.assertEqual(self.state(tid)["state"], "ACCEPTED")

    def test_research_text_flow_checks_actual_quoted_content(self):
        tid = str(uuid.uuid4())
        self.system.submit(tid, "analyze_text", {"text": "Measured reachable area: 30.3%.", "question": "What was measured?"})
        self.system.tick(); self.system.tick()
        self.assertEqual(self.state(tid)["state"], "ACCEPTED")
        spec = json.loads(self.state(tid)["spec"])
        artifact = read_json(self.runtime/"tasks"/tid/"artifact.json")
        artifact["citations"][0]["quote"] = "Invented result"
        self.assertFalse(self.system.valid_artifact(spec, artifact))

    def test_research_text_bad_offsets_cannot_pass(self):
        tid = str(uuid.uuid4())
        self.system.submit(tid, "analyze_text", {"text": "abc", "question": "What is the evidence?"})
        spec = json.loads(self.state(tid)["spec"])
        artifact = {"task_id": tid, "input_sha256": spec["input_sha256"],
                    "source_sha256": spec["source"]["sha256"], "summary": "This is an analysis.",
                    "citations": [{"quote": "abc", "start": -1, "end": 3}]}
        self.assertFalse(self.system.valid_artifact(spec, artifact))
        artifact["citations"][0] = {"quote": "abc", "start": False, "end": 3}
        self.assertFalse(self.system.valid_artifact(spec, artifact))

    def test_wrong_result_exit_zero_rejected_and_rework_limit(self):
        tid = self.submit()
        self.bad = True
        for _ in range(8):
            self.system.tick()
        row = self.state(tid)
        self.assertEqual(row["state"], "NEEDS_ATTENTION")
        self.assertEqual(row["reworks"], 2)
        self.assertEqual(len(self.calls), 3)
        self.assertFalse((self.runtime/"tasks"/tid/"acceptance.json").exists())

    def test_duplicate_submission_runs_once(self):
        tid = self.submit()
        self.submit(tid)
        for _ in range(5):
            self.system.tick()
        self.assertEqual(self.calls, ["codex", "claude"])

    def test_duplicate_id_changed_input_rejected(self):
        tid = self.submit()
        with self.assertRaises(ValueError):
            self.system.submit(tid, "analyze_numbers", [999])

    def test_duplicate_trigger_lock_skips_dispatch(self):
        self.submit()
        with self.system.lock():
            receipt = self.system.tick()
        self.assertEqual(receipt, {"skipped": "INSTANCE_ALREADY_RUNNING"})
        self.assertEqual(self.calls, [])

    def test_lock_releases_on_exception(self):
        try:
            with self.system.lock():
                raise RuntimeError()
        except RuntimeError:
            pass
        with self.system.lock():
            pass

    def test_crash_before_pid_no_replay(self):
        tid = self.submit()
        self.system.state(tid, "EXECUTING")
        self.system.tick()
        self.assertEqual(self.state(tid)["state"], "NEEDS_ATTENTION")
        self.assertEqual(self.calls, [])
        self.assertIsNotNone(self.system.meta("paused"))

    def test_real_controller_crash_does_not_replay_owned_child(self):
        tid = self.submit()
        process_file = self.base/"crashed-child.json"
        script = '''
import json,os,sys
from pathlib import Path
from researchops.core import System,utc
from researchops.winproc import run_owned
s=System(Path(sys.argv[1]),Path(sys.argv[2]))
tid=sys.argv[3]
with s.lock():
 s.state(tid,'EXECUTING')
 def started(pid,birth):
  s.db.execute("INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?,?,?)",('crash-attempt',tid,'execute','codex','crash-session',pid,birth,'RUNNING',utc(),None))
  s.db.commit()
  Path(sys.argv[4]).write_text(json.dumps({'pid':pid,'birth':birth}))
  os._exit(23)
 run_owned([sys.executable,'-c','import time;time.sleep(30)'],'',Path.cwd(),os.environ.copy(),10,started,256)
'''
        p = subprocess.run([sys.executable, "-c", script, str(self.source), str(self.runtime), tid,
                            str(process_file)], cwd=ROOT, creationflags=0x08000000, timeout=10)
        self.assertEqual(p.returncode, 23)
        child = read_json(process_file)
        # A terminated controller's private job must not leave a live suspended child.
        import time
        for _ in range(20):
            if winproc.identity(child["pid"]) is None: break
            time.sleep(0.05)
        self.assertIsNone(winproc.identity(child["pid"]))
        self.system.tick()
        self.assertEqual(self.state(tid)["state"], "NEEDS_ATTENTION")
        self.assertEqual(self.calls, [])

    def make_orphan(self, pid, birth):
        tid = self.submit()
        self.system.state(tid, "EXECUTING")
        self.system.db.execute("INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), tid, "execute", "codex", str(uuid.uuid4()), pid, birth, "RUNNING", utc(), None))
        self.system.db.commit()
        return tid

    def test_recovery_identifies_live_original_process(self):
        tid = self.make_orphan(os.getpid(), winproc.identity(os.getpid()))
        self.system.tick()
        self.assertEqual(self.state(tid)["reason"], "ORPHAN_ALIVE")
        self.assertEqual(self.calls, [])
        self.assertIsNotNone(winproc.identity(os.getpid()))

    def test_recovery_dead_and_pid_reuse_never_replay(self):
        tid = self.make_orphan(os.getpid(), "different_birth")
        self.system.tick()
        self.assertEqual(self.state(tid)["reason"], "AMBIGUOUS_COMPLETION_NO_REPLAY")
        self.assertEqual(self.calls, [])

    def test_recovery_inaccessible_is_unknown(self):
        tid = self.make_orphan(999, "birth")
        with patch("researchops.winproc.identity", return_value="UNKNOWN"):
            self.system.tick()
        self.assertEqual(self.state(tid)["reason"], "ORPHAN_UNKNOWN")

    def test_simulated_network_failure_pauses_without_retry(self):
        tid = self.submit()
        self.call_failure = "NETWORK"
        for _ in range(3): self.system.tick()
        self.assertEqual(self.state(tid)["state"], "WAITING_CODEX")
        self.assertEqual(self.system.engine_paused("codex")["reason"], "NETWORK")
        self.assertEqual(len(self.calls), 1)

    def test_simulated_login_failure_pauses_without_retry(self):
        tid = self.submit()
        self.call_failure = "AUTH"
        for _ in range(3): self.system.tick()
        self.assertEqual(self.state(tid)["state"], "WAITING_CODEX")
        self.assertEqual(self.system.engine_paused("codex")["reason"], "AUTH")
        self.assertEqual(len(self.calls), 1)

    def test_simulated_quota_failure_pauses(self):
        tid = self.submit()
        self.call_failure = "QUOTA"
        self.system.tick(); self.system.tick()
        self.assertEqual(self.state(tid)["state"], "WAITING_CODEX")
        self.assertEqual(self.system.engine_paused("codex")["reason"], "QUOTA")
        self.assertEqual(len(self.calls), 1)

    def test_optional_local_engine_cap_is_persistent_and_per_engine(self):
        self.limit(codex=20)
        for _ in range(20): self.system.reserve("test", engine="codex")
        other = System(self.source, self.runtime, self.fake)
        try:
            with self.assertRaises(adapters.CallError) as cm:
                other.reserve("21st", engine="codex")
            self.assertEqual(cm.exception.kind, "BUDGET")
            other.reserve("claude is not capped", engine="claude")  # a cap on one engine never blocks the other
        finally:
            other.close()
        tid = self.submit()
        self.system.tick()
        self.assertEqual(self.state(tid)["state"], "WAITING_CODEX")
        self.assertEqual(self.system.db.execute("SELECT launched FROM task_waits WHERE task=?", (tid,)).fetchone()[0], 0)
        self.assertEqual(self.calls, [])

    def test_stale_source_even_without_commit_change(self):
        tid = self.submit()
        self.system.tick()
        (self.source/"untracked.py").write_text("changed=True", encoding="utf-8")
        self.system.tick()
        self.assertEqual(self.state(tid)["reason"], "STALE_SOURCE_OR_INPUT")
        self.assertEqual(len(self.calls), 1)

    def test_stale_runtime_input_rejected(self):
        tid = self.submit()
        path = self.runtime/"tasks"/tid/"spec.json"
        spec = read_json(path); spec["input"] = [999]; write_json(path, spec)
        self.system.tick()
        self.assertEqual(self.state(tid)["reason"], "STALE_SOURCE_OR_INPUT")
        self.assertEqual(self.calls, [])

    def test_stale_review_during_call_rejected(self):
        tid = self.submit()
        self.system.tick()
        self.on_review = lambda: (self.source/"code.py").write_text("version=2", encoding="utf-8")
        self.system.tick()
        self.assertEqual(self.state(tid)["reason"], "STALE_REVIEW")
        self.assertFalse((self.runtime/"tasks"/tid/"acceptance.json").exists())

    def test_artifact_tamper_during_review_rejected(self):
        tid = self.submit(); self.system.tick()
        self.on_review = lambda: write_json(self.runtime/"tasks"/tid/"artifact.json", {"sum": 42})
        self.system.tick()
        self.assertEqual(self.state(tid)["reason"], "STALE_REVIEW")

    def test_unchanged_observation_calls_no_models(self):
        for _ in range(3): self.system.tick()
        self.assertEqual(self.calls, [])
        self.assertFalse(read_json(self.runtime/"observation.json")["changed"])

    def test_pause_resume_do_not_retry_failed_task(self):
        tid = self.submit(); self.call_failure = "AUTH"; self.system.tick()
        self.call_failure = None; self.system.resume(); self.system.tick()
        self.assertEqual(len(self.calls), 1)  # a global resume never resumes an engine wait
        self.assertEqual(self.state(tid)["state"], "WAITING_CODEX")

    def test_explicit_retry_refuses_live_original(self):
        tid = self.make_orphan(os.getpid(), winproc.identity(os.getpid()))
        self.system.state(tid, "PAUSED_NETWORK")
        with self.assertRaises(ValueError): self.system.requeue_paused(tid)

    def test_unauthorized_commands_and_paths_rejected(self):
        for action in ("bash", "ssh", "gpu", "publish", "edit", "../../escape"):
            with self.assertRaises(ValueError): self.system.submit(str(uuid.uuid4()), action, [])
        with self.assertRaises(ValueError): self.system.submit("../escape", "analyze_numbers", [])

    def test_wrong_types_do_not_pass_as_numbers(self):
        with self.assertRaises(ValueError): expected("analyze_numbers", [True])
        with self.assertRaises(ValueError): expected("analyze_numbers", [2**80])
        self.assertEqual(expected("inspect_text", "a b\nc\n"), {"line_count": 2, "word_count": 3})

    def test_source_manifest_covers_templates_excludes_runtime(self):
        first = manifest(self.source)
        (self.source/".runtime").mkdir()
        (self.source/".runtime/noise").write_text("noise")
        self.assertEqual(first, manifest(self.source))
        (self.source/"prompts/review.txt").write_text("changed")
        self.assertNotEqual(first, manifest(self.source))

    def test_snapshot_tamper_fails(self):
        source = manifest(self.source)
        write_json(self.runtime/"machine.json", {})
        write_json(self.runtime/"activation.json", {"owner": "BGV.Windows.ResearchOps.v1",
                   "source_sha256": source["sha256"], "source": str(self.source),
                   "source_manifest": source, "machine_sha256": digest(canonical({}))})
        verify_activation(self.source, self.runtime, source["sha256"])
        (self.source/"code.py").write_text("tampered")
        with self.assertRaises(ValueError): verify_activation(self.source, self.runtime, source["sha256"])

    def test_stale_test_evidence_cannot_be_reviewed(self):
        p = self.runtime/"tests.json"
        write_json(p, {"success": True, "source_sha256": "stale"})
        with self.assertRaises(ValueError): review_package(self.system, p)

    def test_pause_resume_and_retry_leave_event_records(self):
        tid = self.submit(); self.call_failure = "CLI"; self.system.tick(); self.call_failure = None
        self.system.pause("OPERATOR"); self.system.resume()
        self.system.requeue_paused(tid)
        events = [(r["event"], json.loads(r["detail"])) for r in self.system.db.execute(
            "SELECT event,detail FROM events WHERE event LIKE 'DISPATCH_%' ORDER BY seq")]
        self.assertEqual([e for e, _ in events], ["DISPATCH_PAUSED", "DISPATCH_RESUMED", "DISPATCH_RESUMED"])
        self.assertEqual(events[0][1], {"reason": "OPERATOR"})
        self.assertEqual(events[1][1]["previous"], {"reason": "OPERATOR"})
        self.assertEqual(events[2][1]["by"], "explicit_retry")

    def audit_evidence(self):
        write_json(self.runtime/"tests.json", {"success": True, "source_sha256": manifest(self.source)["sha256"]})
        return self.runtime/"tests.json"

    def audit(self, verdict=None, failure=None, reviewer="claude", cycle=None, value=None):
        evidence = self.audit_evidence()
        seen = []
        def invoke(engine, machine, policy, prompt, schema, cwd, on_start, session, effort=None):
            self.assertEqual(effort, "medium")
            seen.append(engine)
            if failure == "CRASH":
                raise RuntimeError("controller died during the audit call")
            if failure:
                raise adapters.CallError(failure)
            binding = read_json(Path(cwd)/"package.json")["binding_sha256"]
            if value is not None:
                return value(binding), {"exit_code": 0, "session_id": session}
            return ({"binding_sha256": binding, "verdict": verdict, "issues": [] if verdict == "PASS" else ["x"]},
                    {"exit_code": 0, "session_id": session})
        with patch.object(deployment, "verify_repo", return_value={}), \
             patch.object(deployment.adapters, "invoke", invoke):
            result = deployment.independent_review(self.system, evidence, reviewer, cycle)
        return result, seen

    def revise(self, n):
        (self.source/"code.py").write_text(f"version = {n}\n", encoding="utf-8")

    def test_audit_rounds_are_bounded_per_revision_cycle(self):
        for n in range(3):
            self.revise(n + 10)
            self.assertEqual(self.audit("REWORK")[0]["status"], "REWORK")
        self.revise(99)
        with self.assertRaises(ValueError): self.audit("PASS")
        self.assertEqual(self.system.calls_today(), 3)

    def freeze_version_1(self):
        self.revise(1); self.audit_evidence()
        with patch.object(deployment, "verify_repo", return_value={}):
            return deployment.freeze(self.system, self.runtime/"tests.json")

    def test_activation_starts_new_cycle_but_refreeze_does_not(self):
        tid = self.submit(); self.system.tick(); self.system.tick()  # accepted dual-CLI task at version 1
        self.assertEqual(self.state(tid)["state"], "ACCEPTED")
        self.revise(10); self.audit("REWORK"); self.revise(11); self.audit("REWORK")
        self.revise(1); self.assertEqual(self.audit("PASS")[0]["status"], "PASS")
        self.freeze_version_1()
        before = (self.runtime/"activation.json").read_bytes()
        # Membership is durable, not timestamp-based: a clock moved behind the approval changes nothing.
        with patch.object(deployment, "utc", return_value="2000-01-01T00:00:00+00:00"):
            for n in range(3):
                self.revise(20 + n); self.audit("REWORK")
            self.revise(30)
            with self.assertRaises(ValueError): self.audit("PASS")
        self.freeze_version_1()  # same approval again
        self.assertEqual((self.runtime/"activation.json").read_bytes(), before)
        self.revise(31)
        with self.assertRaises(ValueError): self.audit("PASS")

    def test_audits_between_approval_and_activation_belong_to_old_cycle(self):
        self.submit(); self.system.tick(); self.system.tick()
        self.assertEqual(self.audit("PASS")[0]["status"], "PASS")  # approval of version 1
        self.revise(10); self.audit("REWORK"); self.revise(11); self.audit("REWORK")
        self.revise(12)
        with self.assertRaises(ValueError): self.audit("PASS")
        self.freeze_version_1()  # activating the approved revision starts a fresh cycle
        for n in range(3):
            self.revise(20 + n); self.assertEqual(self.audit("REWORK")[0]["status"], "REWORK")
        self.revise(30)
        with self.assertRaises(ValueError): self.audit("PASS")

    def test_pause_changes_commit_atomically_with_events(self):
        tid = self.submit(); self.call_failure = "CLI"; self.system.tick(); self.call_failure = None
        import sqlite3
        def committed():
            other = sqlite3.connect(self.runtime/"queue.sqlite3")
            try:
                return (other.execute("SELECT value FROM meta WHERE key='paused'").fetchone()[0],
                        other.execute("SELECT state,reworks FROM tasks WHERE id=?", (tid,)).fetchone(),
                        other.execute("SELECT count(*) FROM events").fetchone()[0])
            finally:
                other.close()
        original = System.event
        def crash(self, event, *a, **k):
            if event.startswith("DISPATCH_"):
                raise RuntimeError("simulated crash before the event commit")
            return original(self, event, *a, **k)
        for operation in (lambda: self.system.pause("OPERATOR"), self.system.resume,
                          lambda: self.system.requeue_paused(tid)):
            before = committed()
            with patch.object(System, "event", crash):
                with self.assertRaises(RuntimeError): operation()
            self.system.db.rollback()  # what process exit does to the open transaction
            self.assertEqual(committed(), before)

    def test_failed_and_crashed_audits_count_as_rounds(self):
        with self.assertRaises(adapters.CallError): self.audit(failure="TIMEOUT")
        self.assertEqual(read_json(next((self.runtime/"independent-review").glob("*/result.json")))["verdict"], "FAILED")
        self.assertEqual(self.system.meta("paused"), {"reason": "TIMEOUT"})
        self.revise(10)
        with self.assertRaises(RuntimeError): self.audit(failure="CRASH")  # no result.json written
        self.assertEqual(deployment.review_rounds(self.system), 2)
        self.revise(11); self.audit("REWORK")
        self.revise(12)
        with self.assertRaises(ValueError): self.audit("PASS")

    def test_audit_reviewer_is_selectable_and_bounded(self):
        self.assertEqual(self.audit("PASS", reviewer="codex")[1], ["codex"])
        with self.assertRaises(ValueError): self.audit("PASS", reviewer="gpt-anything")

    # --- Upgrading a runtime whose audits predate the durable counter -------------------
    def legacy_audit(self, result=None, package=True, call=True):
        """Evidence exactly as the pre-counter revision left it: folder, package, budget call."""
        binding = digest(uuid.uuid4().bytes)
        folder = self.runtime/"independent-review"/binding
        folder.mkdir(parents=True)
        if package:
            write_json(folder/"package.json", {"binding_sha256": binding})
        if result:
            write_json(folder/"result.json", result)
        if call:
            self.system.reserve(deployment.AUDIT_CALL + binding, engine="codex")
        return binding

    def cycle_events(self, name):
        return [json.loads(r[0]) for r in self.system.db.execute(
            "SELECT detail FROM events WHERE event=? ORDER BY seq", (name,))]

    def assert_refused_without_cost(self, message=None):
        calls = self.system.calls_today()
        folders = len(list((self.runtime/"independent-review").glob("*")))
        self.revise(uuid.uuid4().int % 10**6)
        with self.assertRaises(ValueError) as cm: self.audit("PASS")
        self.assertEqual(self.system.calls_today(), calls)
        self.assertEqual(len(list((self.runtime/"independent-review").glob("*"))), folders)
        if message:
            self.assertIn(message, str(cm.exception))

    def test_migration_fresh_runtime_starts_at_zero(self):
        self.assertEqual(self.audit("REWORK")[0]["status"], "REWORK")
        self.assertEqual([e["rounds"] for e in self.cycle_events("AUDIT_CYCLE_MIGRATED")], [0])
        self.assertEqual(self.system.meta("audit_cycle"), {"rounds": 1})

    def test_migration_two_prior_audits_leave_one_round(self):
        self.legacy_audit({"verdict": "FAILED", "kind": "TIMEOUT"})
        self.legacy_audit({"review": {"verdict": "PASS"}})
        self.revise(10); self.assertEqual(self.audit("REWORK")[0]["status"], "REWORK")
        self.assertEqual(self.system.meta("audit_cycle"), {"rounds": 3})
        self.assert_refused_without_cost("exhausted")

    def test_migration_three_or_more_prior_audits_refuse(self):
        for _ in range(4):
            self.legacy_audit({"review": {"verdict": "REWORK"}})
        self.assert_refused_without_cost("exhausted")
        self.assertEqual(self.system.meta("audit_cycle"), {"rounds": 4})  # migration itself persisted

    def test_migration_counts_failed_crashed_and_resultless_attempts(self):
        self.legacy_audit({"verdict": "FAILED", "kind": "NETWORK"})
        self.legacy_audit()                           # crashed after the call: no result.json
        self.legacy_audit(package=False, call=False)  # crashed right after mkdir
        (self.runtime/"independent-review"/"initial-timeout-note.json").write_text("{}")
        self.assert_refused_without_cost("exhausted")
        migrated = self.cycle_events("AUDIT_CYCLE_MIGRATED")[0]
        self.assertEqual((migrated["rounds"], migrated["notes"]), (3, ["initial-timeout-note.json"]))

    def test_existing_counter_is_not_reinitialized(self):
        for _ in range(4):
            self.legacy_audit({"review": {"verdict": "REWORK"}})
        self.system.set_meta("audit_cycle", {"rounds": 1})
        self.revise(10); self.assertEqual(self.audit("REWORK")[0]["status"], "REWORK")
        self.assertEqual(self.system.meta("audit_cycle"), {"rounds": 2})
        self.assertEqual(self.cycle_events("AUDIT_CYCLE_MIGRATED"), [])

    def test_refreeze_of_active_legacy_approval_cannot_reset_migrated_count(self):
        self.submit(); self.system.tick(); self.system.tick()
        self.assertEqual(self.audit("PASS")[0]["status"], "PASS")
        self.freeze_version_1()
        # Turn this into a pre-counter runtime: the old revision wrote no counter or cycle events.
        self.system.db.execute("DELETE FROM meta WHERE key='audit_cycle'")
        self.system.db.execute("DELETE FROM events WHERE event LIKE 'AUDIT_%'")
        self.system.db.commit()
        self.legacy_audit({"verdict": "FAILED", "kind": "TIMEOUT"})
        before = (self.runtime/"activation.json").read_bytes()
        self.freeze_version_1()  # identical approval: no rewrite, no reset
        self.assertEqual((self.runtime/"activation.json").read_bytes(), before)
        self.assertIsNone(self.system.meta("audit_cycle"))
        self.revise(10); self.assertEqual(self.audit("REWORK")[0]["status"], "REWORK")  # 2 migrated + 1
        self.freeze_version_1()
        self.assert_refused_without_cost("exhausted")

    def test_deleting_the_counter_does_not_buy_rounds(self):
        self.revise(10); self.audit("REWORK")
        self.system.db.execute("DELETE FROM meta WHERE key='audit_cycle'"); self.system.db.commit()
        self.assert_refused_without_cost("missing after cycle events")

    def test_unconfirmable_history_refuses(self):
        cases = {
            "corrupt package": lambda b: (self.runtime/"independent-review"/b/"package.json").write_text("{not json"),
            "corrupt result": lambda b: (self.runtime/"independent-review"/b/"result.json").write_text("{"),
            "package for another binding": lambda b: write_json(self.runtime/"independent-review"/b/"package.json", {"binding_sha256": "0"*64}),
            "budgeted call without evidence": lambda b: shutil.rmtree(self.runtime/"independent-review"/b),
            "unknown entry": lambda b: (self.runtime/"independent-review"/"not-a-binding").mkdir(),
            "invalid counter": lambda b: self.system.set_meta("audit_cycle", {"rounds": "0"}),
        }
        for label, damage in cases.items():
            with self.subTest(label):
                self.system.db.execute("DELETE FROM meta WHERE key='audit_cycle'"); self.system.db.commit()
                shutil.rmtree(self.runtime/"independent-review", ignore_errors=True)
                self.system.db.execute("DELETE FROM calls"); self.system.db.commit()
                damage(self.legacy_audit({"verdict": "FAILED", "kind": "CLI"}))
                self.assert_refused_without_cost("refusing")

    def test_migration_commits_atomically_with_the_round_charge(self):
        self.legacy_audit({"verdict": "FAILED", "kind": "TIMEOUT"})
        original = System.event
        def crash(self, event, *a, **k):
            if event == "AUDIT_ROUND_CHARGED":
                raise RuntimeError("simulated crash before commit")
            return original(self, event, *a, **k)
        with patch.object(System, "event", crash):
            with self.assertRaises(RuntimeError): self.audit("PASS")
        self.system.db.rollback()  # what process exit does to the open transaction
        self.assertIsNone(self.system.meta("audit_cycle"))
        self.assertEqual(self.cycle_events("AUDIT_CYCLE_MIGRATED"), [])
        self.assertEqual(self.audit("REWORK")[0]["status"], "REWORK")
        self.assertEqual(self.system.meta("audit_cycle"), {"rounds": 2})

    # === Budget rules and stage-preserving engine waits ==================================
    def test_codex_beyond_twenty_calls_is_not_refused_locally(self):
        for n in range(25):  # ledger entries only; no CLI is run for this
            self.system.reserve("ledger-%d" % n, engine="codex")
        tid = self.submit()
        self.system.tick()
        self.assertEqual((self.state(tid)["state"], self.calls), ("AWAITING_REVIEW", ["codex"]))
        report = self.system.report(persist=False)
        self.assertEqual(report["engine_calls_today"], {"codex": 26, "claude": 0})
        self.assertEqual(report["engine_daily_limits"], {"codex": None, "claude": None})
        rows = self.system.db.execute("SELECT engine,task,stage FROM call_engines WHERE task=?", (tid,)).fetchall()
        self.assertEqual([tuple(r) for r in rows], [("codex", tid, "execute")])

    def test_claude_quota_pauses_only_claude_work(self):
        first = self.submit(); self.system.tick()
        self.engine_failure = {"claude": "QUOTA"}
        self.system.tick()
        self.assertEqual(self.state(first)["state"], "WAITING_CLAUDE")
        self.assertEqual(self.system.engine_paused("claude")["reason"], "QUOTA")
        self.assertIsNone(self.system.meta("paused"))  # no global lock
        second = self.submit()
        self.system.tick()  # independent Codex work continues
        self.assertEqual(self.state(second)["state"], "AWAITING_REVIEW")
        self.system.tick(); self.system.tick()  # but no Claude review is started while Claude waits
        self.assertEqual(self.calls, ["codex", "claude", "codex"])
        self.assertFalse((self.runtime/"tasks"/second/"acceptance.json").exists())

    def test_review_not_launched_resumes_next_day_without_reexecution(self):
        self.limit(claude=1)
        self.system.reserve("earlier claude call", engine="claude")
        tid = self.submit(); self.system.tick()
        self.system.tick()  # review refused by the local cap before any process exists
        wait = self.system.db.execute("SELECT stage,prior,kind,launched FROM task_waits WHERE task=?", (tid,)).fetchone()
        self.assertEqual((self.state(tid)["state"], tuple(wait)), ("WAITING_CLAUDE", ("review", "AWAITING_REVIEW", "BUDGET", 0)))
        self.assertTrue((self.runtime/"tasks"/tid/"artifact.json").exists())
        self.system.db.execute("UPDATE calls SET day='2000-01-01'"); self.system.db.commit()  # the next UTC day
        resumed = self.system.resume_engine("claude")["resumed"]
        self.assertEqual(resumed, {tid: "AWAITING_REVIEW"})
        self.system.tick()
        self.assertEqual((self.state(tid)["state"], self.state(tid)["reworks"]), ("ACCEPTED", 0))
        self.assertEqual(self.calls, ["codex", "claude"])  # execution ran once
        stages = [r[0] for r in self.system.db.execute("SELECT stage FROM attempts WHERE task=? ORDER BY created", (tid,))]
        self.assertEqual(stages, ["execute", "review"])

    def test_launched_failures_are_recorded_and_resumes_are_bounded(self):
        tid = self.submit(); self.system.tick()
        self.engine_failure = {"claude": "QUOTA"}
        for _ in range(3):
            self.system.tick()
            self.assertEqual(self.system.db.execute("SELECT launched FROM task_waits WHERE task=?", (tid,)).fetchone()[0], 1)
            self.assertEqual(self.system.resume_engine("claude")["resumed"], {tid: "AWAITING_REVIEW"})
        self.system.tick()
        self.assertEqual(self.system.resume_engine("claude")["resumed"], {tid: "NEEDS_ATTENTION"})
        self.assertEqual(self.state(tid)["reason"], "ENGINE_RESUME_LIMIT")
        self.assertEqual(self.calls.count("codex"), 1)  # waiting never re-ran the completed execution

    def test_resume_requires_the_original_process_to_be_gone(self):
        tid = self.submit(); self.system.tick()
        self.engine_failure = {"claude": "TIMEOUT"}; self.system.tick(); self.engine_failure = {}
        self.system.db.execute("UPDATE attempts SET pid=?,birth=? WHERE task=? AND stage='review'",
                               (os.getpid(), winproc.identity(os.getpid()), tid)); self.system.db.commit()
        self.assertEqual(self.system.resume_engine("claude")["resumed"], {tid: "ORIGINAL_PROCESS_NOT_CONFIRMED_GONE"})
        self.assertEqual(self.state(tid)["state"], "WAITING_CLAUDE")

    def test_user_pause_is_never_cleared_by_an_engine_resume(self):
        tid = self.submit(); self.system.tick()
        self.engine_failure = {"claude": "QUOTA"}; self.system.tick(); self.engine_failure = {}
        self.system.pause("OPERATOR")
        self.system.resume_engine("claude")
        self.assertEqual(self.system.meta("paused"), {"reason": "OPERATOR"})
        calls = list(self.calls)
        self.system.tick()
        self.assertEqual((self.calls, self.state(tid)["state"]), (calls, "AWAITING_REVIEW"))

    def test_engine_wait_commits_with_state_pause_and_event(self):
        tid = self.submit(); self.system.tick()
        self.engine_failure = {"claude": "QUOTA"}
        original = System.event
        def crash(system, event, *a, **k):
            if event == "ENGINE_PAUSED":
                raise RuntimeError("simulated crash before commit")
            return original(system, event, *a, **k)
        with patch.object(System, "event", crash):
            with self.assertRaises(RuntimeError):
                self.system.tick()
        self.system.db.rollback()
        self.assertIsNone(self.system.engine_paused("claude"))
        self.assertIsNone(self.system.db.execute("SELECT * FROM task_waits WHERE task=?", (tid,)).fetchone())
        self.engine_failure = {}
        calls = list(self.calls)
        self.system.tick()  # the interrupted stage is quarantined, never replayed
        self.assertEqual((self.state(tid)["state"], self.calls), ("NEEDS_ATTENTION", calls))

    # === Registered scene tools and skills =================================================
    SCENE = {"skill": "stair-template-selection", "scene": "scenesmith-run3-school", "profile": "school", "clearance_m": 0.1}

    def scene_task(self, room):
        tid = str(uuid.uuid4())
        self.system.submit(tid, "scene_stair_workflow", {**self.SCENE, "room": room})
        return tid

    def test_scene_workflow_runs_real_tools_and_accepts_on_content(self):
        guarded = [scene.registry(self.source)[0]["external"]["buildingsgen"]["repository"],
                   r"E:\Github\Research\Scenesmith\outputs\Codex Run\run 3\scene_package\floor_plans\lobby_waiting_area"]
        before = [scene.listing_sha256(g) for g in guarded]
        tid = self.scene_task("lobby_waiting_area")
        self.system.tick(); self.system.tick()
        self.assertEqual((self.state(tid)["state"], self.calls), ("ACCEPTED", ["codex", "claude"]))
        artifact = read_json(self.runtime/"tasks"/tid/"artifact.json")
        self.assertEqual(len(artifact["checks"]), 14)
        self.assertTrue(all(artifact["checks"].values()))
        measured = artifact["measured"]
        self.assertAlmostEqual(measured["target_floor_rise_m"], sum(measured["rises_m"]), places=4)
        self.assertGreater(measured["mesh_bbox_height_m"], measured["target_floor_rise_m"])
        self.assertEqual((measured["observed_min_riser_m"], measured["observed_max_riser_m"]), (0.16, 0.16))
        self.assertEqual((measured["profile_riser_min_m"], measured["profile_riser_max_m"]), (0.15, 0.175))
        self.assertEqual([r["tool"] for r in artifact["tool_runs"]], scene.registry(self.source)[1]["stair-template-selection"]["tools"])
        self.assertTrue(all(0.15 <= r <= 0.175 for r in artifact["measured"]["rises_m"]))
        self.assertIn(artifact["selection"]["template"], [c["family"] for c in artifact["candidates"] if c["fits_room"]])
        self.assertTrue(self.system.valid_artifact(json.loads(self.state(tid)["spec"]), artifact))
        self.assertEqual([scene.listing_sha256(g) for g in guarded], before)  # inputs untouched
        # Acceptance rests on content: changing a produced file or a check breaks it.
        spec = json.loads(self.state(tid)["spec"])
        stair = next((self.runtime/"tasks"/tid/"work").rglob("stair.build_usd/stair.usda"))
        original = stair.read_bytes()
        stair.write_bytes(original + b"\n")
        self.assertFalse(self.system.valid_artifact(spec, artifact))
        stair.write_bytes(original)
        self.assertTrue(self.system.valid_artifact(spec, artifact))
        self.assertFalse(self.system.valid_artifact(spec, {**artifact, "checks": {**artifact["checks"], "fits_room_with_clearance": False}}))

    def test_scene_room_where_nothing_fits_stops_without_a_model_call(self):
        tid = self.scene_task("stair_entrance")
        self.system.tick()
        self.assertEqual((self.state(tid)["state"], self.state(tid)["reason"], self.calls),
                         ("NEEDS_ATTENTION", "NO_FITTING_TEMPLATE", []))
        report = read_json(next((self.runtime/"tasks"/tid/"work").rglob("no-fit-report.json")))
        self.assertFalse(any(c["fits_room"] for c in report["candidates"]["candidates"]))
        u = next(c for c in report["candidates"]["candidates"] if c["family"] == "u_shaped")
        self.assertGreater(u["footprint_sorted_m"][1], u["library_footprint_sorted_m"][1])  # measured, not trusted

    def test_scene_model_choice_outside_fitting_templates_is_rejected(self):
        tid = self.scene_task("lobby_waiting_area")
        self.scene_choice = "spiral"
        self.system.tick()
        self.assertEqual((self.state(tid)["state"], self.state(tid)["reason"]), ("REWORK", "SELECTION_REJECTED"))
        self.assertFalse((self.runtime/"tasks"/tid/"artifact.json").exists())
        self.assertFalse(list((self.runtime/"tasks"/tid/"work").rglob("stair.build_usd")))  # nothing built

    def test_scene_inputs_parameters_and_paths_are_constrained(self):
        for change in ({"room": "../stair_entrance"}, {"room": "library"}, {"scene": "other"}, {"skill": "graphify"},
                       {"profile": "warehouse"}, {"clearance_m": -0.1}, {"extra": "x"}):
            with self.subTest(change):
                with self.assertRaises(ValueError):
                    self.system.submit(str(uuid.uuid4()), "scene_stair_workflow", {**self.SCENE, "room": "lobby_waiting_area", **change})
        tools = scene.registry(self.source)[0]["tools"]
        for tool, params in (("stair.build_usd", {"profile": "school", "rise_m": 3.2, "family": "spiral"}),
                             ("stair.build_usd", {"profile": "school", "rise_m": 30.0, "family": "u_shaped"}),
                             ("stair.build_usd", {"profile": "school", "rise_m": 3.2, "family": "u_shaped", "cmd": "x"}),
                             ("scene.room_meshes", {"scene": "a b;rm", "room": "x"})):
            with self.subTest(tool=tool, params=params):
                with self.assertRaises(ValueError):
                    scene.validate_params(tools[tool], params)
        tid = self.scene_task("lobby_waiting_area")
        spec = json.loads(self.state(tid)["spec"])
        with self.assertRaisesRegex(ValueError, "Unregistered tool"):
            scene.run_tool(self.system, spec, "shell.exec", {}, self.runtime/"tasks"/tid/"work")
        with self.assertRaisesRegex(ValueError, "inside the task workdir"):
            scene.run_tool(self.system, spec, "stair.build_usd", {"profile": "school", "rise_m": 3.2, "family": "u_shaped"},
                           self.base/"outside")

    def test_skill_or_external_version_change_invalidates_bindings(self):
        tid = self.scene_task("lobby_waiting_area")
        self.system.tick(); self.system.tick()
        spec = json.loads(self.state(tid)["spec"])
        artifact = read_json(self.runtime/"tasks"/tid/"artifact.json")
        self.assertTrue(self.system.valid_artifact(spec, artifact))
        skill = self.source/"skills/stair-template-selection.md"
        text = skill.read_text(encoding="utf-8")
        skill.write_text(text + "\nchanged rule\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "External binding changed"):
            scene.check_bindings(self.source)
        self.assertFalse(self.system.valid_artifact(spec, artifact))
        with self.assertRaises(ValueError):
            self.system.submit(str(uuid.uuid4()), "scene_stair_workflow", {**self.SCENE, "room": "lobby_waiting_area"})
        skill.write_text(text, encoding="utf-8")
        tools_path = self.source/"config/tools.json"
        registry = read_json(tools_path)
        registry["external"]["buildingsgen"]["sha256"] = "0" * 64
        write_json(tools_path, registry)
        with self.assertRaisesRegex(ValueError, "buildingsgen"):
            scene.check_bindings(self.source)

    def test_tool_run_fails_if_a_read_only_tree_changes(self):
        tid = self.scene_task("lobby_waiting_area")
        spec = json.loads(self.state(tid)["spec"])
        real, seen = scene.listing_sha256, []
        def drifting(path):
            seen.append(path)
            return real(path) + ("x" if len(seen) > 2 else "")
        with patch.object(scene, "listing_sha256", drifting):
            with self.assertRaisesRegex(scene.ToolFailure, "Read-only research input changed"):
                scene.run_tool(self.system, spec, "stair.build_usd", {"profile": "school", "rise_m": 3.2, "family": "u_shaped"},
                               self.runtime/"tasks"/tid/"work"/"probe")

    def test_cycle_rework_rounds_are_bounded_by_the_authorization(self):
        self.fake_activation()
        self.system.set_meta("audit_cycle", {"rounds": 3})
        with self.assertRaises(ValueError):
            deployment.authorize_cycle(self.system, str(uuid.uuid4()), str(uuid.uuid4()), "x" * 30, "codex", 4)
        cycle = str(uuid.uuid4())
        deployment.authorize_cycle(self.system, cycle, self.cycle_task(cycle), "Three audits are authorized here.", "codex", 3)
        for n in range(2):
            self.revise(60 + n)
            self.assertEqual(self.audit("REWORK", reviewer="codex", cycle=cycle)[0]["status"], "REWORK")
            self.assertEqual(self.system.cycle(cycle)[1], "OPEN")  # another authorized round remains
        self.revise(62)
        self.assertEqual(self.audit("REWORK", reviewer="codex", cycle=cycle)[0]["status"], "REWORK")
        self.assertEqual((self.system.cycle(cycle)[1], self.system.cycle(cycle)[0]["used"]["audit"]), ("CLOSED_REWORK", 3))
        calls = self.system.calls_today()
        self.revise(63)
        with self.assertRaises(ValueError):
            self.audit("PASS", reviewer="codex", cycle=cycle)
        self.assertEqual((self.system.calls_today(), self.system.meta("audit_cycle")), (calls, {"rounds": 3}))
        with self.assertRaises(ValueError):  # re-registering with a larger allowance is refused
            deployment.authorize_cycle(self.system, cycle, self.cycle_task(cycle), "Three audits are authorized here.", "codex", 2)

    def test_freeze_accepts_a_verified_scene_task(self):
        tid = self.scene_task("lobby_waiting_area")
        self.system.tick(); self.system.tick()
        self.assertEqual(self.state(tid)["state"], "ACCEPTED")
        self.assertEqual(self.audit("PASS")[0]["status"], "PASS")
        self.audit_evidence()
        with patch.object(deployment, "verify_repo", return_value={}):
            activation = deployment.freeze(self.system, self.runtime/"tests.json")
        self.assertEqual(activation["dual_cli_tasks"], [tid])
        snapshot = Path(activation["source"])
        self.assertTrue((snapshot/"researchops/scene_runner.py").exists() and (snapshot/"skills/stair-template-selection.md").exists())

    # === Audit round 1 findings (e9552b1f) =================================================
    def test_tool_process_cannot_write_outside_its_output_directory(self):
        allowed, forbidden = self.base/"tool-out", self.base/"elsewhere"
        allowed.mkdir(); forbidden.mkdir()
        winproc.label_low(allowed)
        script = ("import json,sys\nres={}\nfor k,p in (('allowed',sys.argv[1]),('forbidden',sys.argv[2])):\n"
                  " try:\n  open(p,'w').write('x'); res[k]='written'\n except OSError as e:\n  res[k]=type(e).__name__\n"
                  "print(json.dumps(res))")
        rc, out, _, _ = winproc.run_owned([sys.executable, "-I", "-B", "-c", script, str(allowed/"a"), str(forbidden/"b")],
                                          "", allowed, dict(os.environ), 30, lambda p, b: None, 256, low_integrity=True)
        self.assertEqual((rc, json.loads(out)), (0, {"allowed": "written", "forbidden": "PermissionError"}))
        self.assertEqual(list(forbidden.iterdir()), [])

    def test_cli_accepts_the_documented_scene_submission(self):
        out = subprocess.run([sys.executable, str(ROOT/"researchops.py"), "submit", "--help"], capture_output=True,
                             text=True, creationflags=0x08000000, timeout=60).stdout
        self.assertIn("scene_stair_workflow", out)

    def test_scene_report_values_are_bound_to_tool_results(self):
        tid = self.scene_task("lobby_waiting_area")
        self.system.tick(); self.system.tick()
        spec = json.loads(self.state(tid)["spec"])
        artifact = read_json(self.runtime/"tasks"/tid/"artifact.json")
        self.assertTrue(self.system.valid_artifact(spec, artifact))
        lied = json.loads(json.dumps(artifact)); lied["measured"]["rises_m"][0] = 0.12
        self.assertFalse(self.system.valid_artifact(spec, lied))
        lied = json.loads(json.dumps(artifact)); lied["inventory"]["interior_m"] = [9.0, 9.0]
        self.assertFalse(self.system.valid_artifact(spec, lied))
        lied = json.loads(json.dumps(artifact)); lied["not_verified"] = []
        self.assertFalse(self.system.valid_artifact(spec, lied))
        lied = json.loads(json.dumps(artifact))
        for c in lied["candidates"]:
            if c["family"] == artifact["selection"]["template"]:
                c["fits_room"] = False
        self.assertFalse(self.system.valid_artifact(spec, lied))
        lied = json.loads(json.dumps(artifact)); lied["candidates"][0]["margin_m"] = [9.9, 9.9]
        self.assertFalse(self.system.valid_artifact(spec, lied))
        build = artifact["tool_runs"][2]
        usda = next(rel for rel in build["outputs"] if rel.endswith("stair.usda"))
        lied = json.loads(json.dumps(artifact)); del lied["tool_runs"][2]["outputs"][usda]
        self.assertFalse(self.system.valid_artifact(spec, lied))  # a registered output must be accounted for
        extra = self.runtime/"tasks"/tid/"work"/usda.split("/")[0]/"stair.build_usd"/"late.txt"
        extra.write_text("added after the run", encoding="utf-8")
        self.assertFalse(self.system.valid_artifact(spec, artifact))
        extra.unlink()
        self.assertTrue(self.system.valid_artifact(spec, artifact))

    def test_stair_check_enforces_the_minimum_riser(self):
        tid = self.scene_task("lobby_waiting_area")
        self.system.tick(); self.system.tick()
        artifact = read_json(self.runtime/"tasks"/tid/"artifact.json")
        spec = json.loads(self.state(tid)["spec"])
        stair = next((self.runtime/"tasks"/tid/"work").rglob("stair.build_usd/stair.usda"))
        params = dict(artifact["tool_runs"][3]["params"])
        last_top = 3.2 - artifact["measured"]["rises_m"][-1]
        params["rise_m"] = round(last_top + 0.10, 4)  # last rise 0.10 m: below 0.15 m, still below the maximum
        result, _ = scene.run_tool(self.system, spec, "stair.check_usd", params, self.runtime/"tasks"/tid/"work"/"minrise",
                                   {"stair_usda": str(stair)})
        self.assertFalse(result["checks"]["every_rise_within_envelope"])
        self.assertFalse(result["checks"]["first_and_last_rise_within_envelope"])
        self.assertLess(result["measured"]["rises_m"][-1], result["measured"]["profile_riser_min_m"])

    def test_freeze_final_gate_rereads_machine_config(self):
        tid = self.accepted_and_approved()
        real, done = shutil.copyfile, []
        def copy(src, dst, *a, **k):
            if not done:
                done.append(1)
                write_json(self.runtime/"machine.json", {"codex": "swapped.exe"})
            return real(src, dst, *a, **k)
        with patch.object(deployment.shutil, "copyfile", copy):
            with self.assertRaises(ValueError):
                self.freeze_version_1()
        self.assert_no_publication()

    def test_freeze_rejects_missing_engine_ledger_row(self):
        def damage(tid, d):
            self.system.db.execute("DELETE FROM call_engines WHERE task=? AND stage='review'", (tid,)); self.system.db.commit()
        self.freeze_should_fail(damage)

    # === Audit round 2 findings (69898574) =================================================
    def low_child_writes(self, *paths):
        own = self.base/("own-" + uuid.uuid4().hex[:6]); own.mkdir()
        winproc.label_low(own)
        script = ("import json,sys\nres=[]\nfor p in sys.argv[1:]:\n try:\n  open(p,'w').write('x'); res.append('written')\n"
                  " except OSError as e:\n  res.append(type(e).__name__)\nprint(json.dumps(res))")
        rc, out, _, _ = winproc.run_owned([sys.executable, "-I", "-B", "-c", script, *map(str, paths), str(own/"ok")],
                                          "", own, dict(os.environ), 30, lambda p, b: None, 256, low_integrity=True)
        self.assertEqual(rc, 0)
        return json.loads(out)

    def test_finished_tool_directories_are_not_writable_by_later_tools(self):
        tid = self.scene_task("lobby_waiting_area")
        spec = json.loads(self.state(tid)["spec"])
        scene.run_tool(self.system, spec, "stair.build_usd", {"profile": "school", "rise_m": 3.2, "family": "u_shaped"},
                       self.runtime/"tasks"/tid/"work"/"first")
        done = self.runtime/"tasks"/tid/"work"/"first"/"stair.build_usd"
        self.assertEqual(self.low_child_writes(done/"late.txt", done/"tmp"/"late.txt"), ["PermissionError", "PermissionError", "written"])
        self.assertEqual(self.system.meta("low_labelled"), [])

    def test_low_label_left_by_a_crash_is_restored_before_the_next_run(self):
        stale = self.base/"crashed-run"; stale.mkdir()
        winproc.label_low(stale)
        self.system.set_meta("low_labelled", [str(stale)])
        self.assertEqual(self.low_child_writes(stale/"before.txt")[0], "written")
        tid = self.scene_task("lobby_waiting_area")
        spec = json.loads(self.state(tid)["spec"])
        scene.run_tool(self.system, spec, "stair.build_usd", {"profile": "school", "rise_m": 3.2, "family": "u_shaped"},
                       self.runtime/"tasks"/tid/"work"/"next")
        self.assertEqual(self.low_child_writes(stale/"after.txt")[0], "PermissionError")

    def test_audit_gate_is_durable_and_kept_unless_the_audit_passes(self):
        import sqlite3
        seen = []
        def committed_pause():
            other = sqlite3.connect(self.runtime/"queue.sqlite3")
            try:
                return json.loads(other.execute("SELECT value FROM meta WHERE key='paused'").fetchone()[0])
            finally:
                other.close()
        original = deployment.adapters.invoke
        tid = self.submit()
        self.system.pause("OPERATOR"); self.system.resume()  # no pause before the audit
        def probe(binding):
            seen.append(committed_pause())
            return {"binding_sha256": binding, "verdict": "REWORK", "issues": ["x"]}
        self.revise(70)
        self.assertEqual(self.audit(value=probe)[0]["status"], "REWORK")
        self.assertEqual(seen[0]["reason"], "AUDIT_IN_PROGRESS")  # committed before the CLI ran
        self.assertEqual(self.system.meta("paused")["reason"], "AUDIT_REWORK")
        self.revise(1); self.system.tick()
        self.assertEqual((self.calls, self.state(tid)["state"]), ([], "QUEUED"))  # gate kept: no dispatch
        self.system.resume(); self.system.tick()
        self.assertEqual(self.calls, ["codex"])
        self.system.pause("OPERATOR")
        self.revise(71)
        self.assertEqual(self.audit("PASS")[0]["status"], "PASS")
        self.assertEqual(self.system.meta("paused"), {"reason": "OPERATOR"})  # PASS restores what was there
        self.system.resume()
        self.revise(72)
        with self.assertRaises(RuntimeError):
            self.audit(failure="CRASH")
        self.assertEqual(committed_pause()["reason"], "AUDIT_IN_PROGRESS")  # survives the interruption

    def test_scene_report_changed_during_review_is_not_accepted(self):
        tid = self.scene_task("lobby_waiting_area")
        self.system.tick()
        stair = next((self.runtime/"tasks"/tid/"work").rglob("stair.build_usd/stair.usda"))
        self.on_review = lambda: stair.write_bytes(stair.read_bytes() + b"\n")
        self.system.tick()
        self.assertEqual((self.state(tid)["state"], self.state(tid)["reason"]), ("NEEDS_ATTENTION", "STALE_REVIEW"))
        self.assertFalse((self.runtime/"tasks"/tid/"acceptance.json").exists())

    def test_policy_bounds_tool_limits(self):
        for key, bad in (("tool_timeout_seconds", 0), ("tool_timeout_seconds", 99999), ("tool_memory_mb", 64),
                         ("tool_memory_mb", "4096"), ("max_engine_resumes", 9)):
            with self.subTest(key=key, bad=bad):
                path = self.source/"config/policy.json"
                original = read_json(path)
                write_json(path, {**original, key: bad})
                with self.assertRaisesRegex(ValueError, "exceeds deployment authorization"):
                    System(self.source, self.runtime, self.fake)
                write_json(path, original)

    # === Two-fix task: credential files and the cycle's registered acceptance task ======
    CREDENTIAL_FILES = (".env", ".env.local", "auth.json", "credentials.json", "config/credentials.json",
                        "id_rsa", "id_ed25519.pub", "server.pem", "tools/deploy.key", "store.p12", "Prompts.KDBX",
                        "prompts/token.ppk")

    def test_credential_files_are_refused_before_reading_hashing_or_any_call(self):
        marker = "FAKE-CREDENTIAL-" + uuid.uuid4().hex
        self.submit(); self.system.tick(); self.system.tick()
        real_read, read = Path.read_bytes, []
        def spy(path):
            read.append(path.name)
            return real_read(path)
        for rel in self.CREDENTIAL_FILES:
            with self.subTest(rel):
                path = self.source/rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(marker, encoding="utf-8")
                calls, read[:] = self.system.calls_today(), []
                with patch.object(Path, "read_bytes", spy):
                    with self.assertRaisesRegex(ValueError, "Credential-like file refused before reading"):
                        manifest(self.source)
                self.assertEqual(read, [])  # the decision is made from paths alone
                for action in (lambda: self.audit("PASS"), self.freeze_version_1,
                               lambda: self.system.submit(str(uuid.uuid4()), "analyze_numbers", [1])):
                    with self.assertRaises(ValueError):
                        action()
                self.assertEqual(self.system.calls_today(), calls)  # refused before any budget charge
                self.assertFalse((self.runtime/"independent-review").exists())
                path.unlink()
        self.system.close(); self.system = System(self.source, self.runtime, self.fake)
        self.assertEqual(self.scan(marker), [])
        control = self.base/"scan-control.txt"
        control.write_text(marker, encoding="utf-8")
        self.assertEqual(self.scan(marker), [str(control)])  # the scan can find the marker

    def test_files_outside_the_source_allowlist_refuse_and_new_code_is_bound(self):
        first = manifest(self.source)
        for rel in ("notes.txt", "tools/run.bat", "researchops/sub/extra.py", "config/extra.yaml", "prompts/extra.md"):
            with self.subTest(rel):
                path = self.source/rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("x", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "outside the source allowlist"):
                    manifest(self.source)
                path.unlink()
        for rel in ("researchops/newmod.py", "tools/helper.ps1", "tools/helper.py", "config/extra.json", "prompts/extra.txt"):
            with self.subTest(rel):
                path = self.source/rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("bound = True", encoding="utf-8")
                changed = manifest(self.source)
                self.assertIn(rel, changed["files"])
                self.assertNotEqual(changed["sha256"], first["sha256"])
                path.unlink()
        self.assertEqual(manifest(self.source), first)

    def test_repository_manifest_covers_every_executed_and_read_file(self):
        files = set(manifest(ROOT)["files"])
        executed = {p.relative_to(ROOT).as_posix() for pattern in
                    ("researchops/*.py", "tools/*.ps1", "tools/*.py", "config/*.json", "prompts/*.txt", "*.py", "tests/*.py")
                    for p in ROOT.glob(pattern)}
        self.assertTrue(executed)
        self.assertEqual(executed - files, set())

    def test_cycle_acceptance_task_must_be_the_registered_task_id(self):
        self.fake_activation()
        cycle, _ = self.authorize()
        self.audit("PASS", reviewer="codex", cycle=cycle)
        registered = self.cycle_task(cycle)
        with self.assertRaisesRegex(ValueError, "Cycle does not admit"):
            self.system.submit(str(uuid.uuid4()), "analyze_numbers", [5, 2], "codex", cycle)
        self.assertEqual(self.system.cycle(cycle)[0]["acceptance_task"], None)
        self.system.submit(registered, "analyze_numbers", [5, 2], "codex", cycle)
        events = len(self.cycle_events("SUBMITTED"))
        self.assertEqual(self.system.submit(registered, "analyze_numbers", [5, 2], "codex", cycle), registered)
        self.assertEqual(len(self.cycle_events("SUBMITTED")), events)  # identical resubmission is idempotent
        with self.assertRaises(ValueError):
            self.system.submit(registered, "analyze_numbers", [6], "codex", cycle)
        with self.assertRaises(ValueError):
            self.system.submit(str(uuid.uuid4()), "analyze_numbers", [5, 2], "codex", cycle)
        self.assertEqual(self.system.cycle(cycle)[0]["acceptance_task"], registered)
        self.assertEqual(self.system.db.execute("SELECT count(*) FROM tasks WHERE spec LIKE ?",
                                                ('%"cycle":"' + cycle + '"%',)).fetchone()[0], 1)

    # === Four-fix task: shared helpers =====================================================
    def scan(self, marker):
        needle = marker.encode("utf-8")
        return [str(p) for p in self.base.rglob("*") if p.is_file() and needle in p.read_bytes()]

    def accepted_and_approved(self):
        tid = self.submit(); self.system.tick(); self.system.tick()
        self.assertEqual(self.state(tid)["state"], "ACCEPTED")
        self.assertEqual(self.audit("PASS")[0]["status"], "PASS")
        return tid

    def assert_no_publication(self):
        self.assertFalse((self.runtime/"activation.json").exists())
        snapshots = self.runtime/"snapshots"
        self.assertEqual(list(snapshots.rglob("*")) if snapshots.exists() else [], [])

    def fake_activation(self):
        write_json(self.runtime/"activation.json", {"source_sha256": "a"*64, "approval_binding": "b"*64,
                   "machine_sha256": "c"*64, "time": utc(), "repository": {"commit": "d"*40}})

    def cycle_task(self, cycle):
        return str(uuid.uuid5(uuid.NAMESPACE_URL, cycle))  # the ID authorize() registers

    def authorize(self, reviewer="codex", cycle=None, text="The user explicitly authorizes one bounded review cycle."):
        cycle = cycle or str(uuid.uuid4())
        result = deployment.authorize_cycle(self.system, cycle, str(uuid.uuid5(uuid.NAMESPACE_URL, cycle)), text, reviewer)
        return cycle, result

    # === Defect 1: ownership from process creation =======================================
    def crash_script(self, stage, record, system_args=None):
        head = ("import json,os,sys\nsys.path.insert(0, sys.argv[1])\nfrom researchops import winproc\n"
                "def hook(stage, pid):\n"
                " if stage == sys.argv[3]:\n"
                "  open(sys.argv[2], 'w').write(json.dumps({'pid': pid, 'birth': winproc.identity(pid)}))\n"
                "  os._exit(23)\n"
                "winproc.checkpoint = hook\n")
        if system_args is None:
            body = ("winproc.run_owned([sys.executable, '-c', 'import time; time.sleep(30)'], '', os.getcwd(),\n"
                    "                  dict(os.environ), 20, lambda p, b: None, 256)\n")
            args = []
        else:
            body = ("from pathlib import Path\nfrom researchops.core import System\n"
                    "def caller(engine, machine, policy, prompt, schema, cwd, on_start, session):\n"
                    " return winproc.run_owned([sys.executable, '-c', 'import time; time.sleep(30)'], '', cwd,\n"
                    "                          dict(os.environ), 20, on_start, 256)\n"
                    "s = System(Path(sys.argv[4]), Path(sys.argv[5]), caller)\n"
                    "with s.lock():\n"
                    " s.process(s.db.execute('SELECT * FROM tasks WHERE id=?', (sys.argv[6],)).fetchone())\n")
            args = system_args
        p = subprocess.run([sys.executable, "-c", head + body, str(ROOT), str(record), stage, *args],
                           cwd=ROOT, creationflags=0x08000000, timeout=60)
        self.assertEqual(p.returncode, 23)
        child = read_json(record)
        self.assertNotIn(child["birth"], (None, "UNKNOWN"))
        for _ in range(100):
            if winproc.identity(child["pid"]) is None:
                break
            time.sleep(0.05)
        survivor = winproc.identity(child["pid"])
        if survivor is not None and survivor == child["birth"]:
            # Only this test's own child, identified by PID and creation time, is ever terminated.
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x1, False, child["pid"])
            ctypes.windll.kernel32.TerminateProcess(handle, 1)
            ctypes.windll.kernel32.CloseHandle(handle)
        self.assertIsNone(survivor, "controller death left a live child outside its job")
        return child

    def test_controller_death_right_after_create_leaves_no_child(self):
        self.crash_script("created", self.base/"created.json")

    def test_controller_death_after_registration_leaves_no_child(self):
        self.crash_script("registered", self.base/"registered.json")

    def test_crash_before_pid_record_through_queue_quarantines_without_replay(self):
        for stage, reason in (("created", "START_INTERRUPTED_NO_REPLAY"), ("registered", "AMBIGUOUS_COMPLETION_NO_REPLAY")):
            with self.subTest(stage):
                tid = self.submit()
                self.system.db.execute("UPDATE meta SET value='null' WHERE key='paused'"); self.system.db.commit()
                self.crash_script(stage, self.base/(stage + "-queue.json"),
                                  [str(self.source), str(self.runtime), tid])
                calls = self.system.calls_today()
                self.system.tick(); self.system.tick()
                self.assertEqual((self.state(tid)["state"], self.state(tid)["reason"]), ("NEEDS_ATTENTION", reason))
                self.assertEqual(self.calls, [])
                self.assertEqual(self.system.calls_today(), calls)  # reserved slot kept, nothing replayed

    # === Defect 2: validate before any persistence =======================================
    def test_rejected_model_output_never_reaches_disk(self):
        marker = "FAKE-SECRET-" + uuid.uuid4().hex
        scenarios = [
            ("execute", lambda v: {**v, "leak": marker}),
            ("execute", lambda v: {**v, "sum": marker}),
            ("review", lambda v: {**v, "note": marker}),
            ("review", lambda v: {**v, "issues": [marker]}),                      # PASS with issues
            ("review", lambda v: {**v, "verdict": "REWORK", "issues": [marker], "binding_sha256": "0"*64}),
            ("review", lambda v: {**v, "verdict": "REWORK", "issues": ["x" * 2001 + marker]}),
        ]
        for stage, change in scenarios:
            # Each scenario runs to its rework limit; give it a fresh budget in this temporary runtime only.
            self.system.db.execute("DELETE FROM calls")
            self.system.db.execute("UPDATE meta SET value='null' WHERE key='paused'"); self.system.db.commit()
            tid = self.submit()
            self.mutate = lambda s, v, stage=stage, change=change: change(v) if s == stage else v
            for _ in range(10):
                self.system.tick()
                if self.state(tid)["state"] == "NEEDS_ATTENTION":
                    break
            self.assertEqual(self.state(tid)["state"], "NEEDS_ATTENTION")
            self.assertFalse((self.runtime/"tasks"/tid/"acceptance.json").exists())
        # A well-formed REWORK review is legitimate and is kept under the restricted schema.
        self.system.db.execute("DELETE FROM calls"); self.system.db.commit()
        tid = self.submit()
        self.mutate = lambda s, v: {**v, "verdict": "REWORK", "issues": ["legit issue text"]} if s == "review" else v
        self.system.tick(); self.system.tick()
        self.assertEqual(read_json(self.runtime/"tasks"/tid/"review.json")["review"]["issues"], ["legit issue text"])
        self.system.state(tid, "NEEDS_ATTENTION", "TEST_CASE_DONE")
        self.mutate = None
        # Independent audit: invalid shapes are recorded only as bounded metadata.
        for n, make in enumerate((lambda b: {"binding_sha256": b, "verdict": "PASS", "issues": [], "leak": marker},
                                  lambda b: {"binding_sha256": b, "verdict": marker, "issues": []},
                                  lambda b: {"binding_sha256": marker, "verdict": "PASS", "issues": []})):
            self.revise(40 + n)
            self.assertEqual(self.audit(value=make)[0]["status"], "INVALID")
        self.assertFalse((self.runtime/"approved-review.json").exists())
        # Real adapter parsing path, including unparseable output carrying the marker.
        self.revise(1)
        self.system.db.execute("UPDATE meta SET value='null' WHERE key='paused'"); self.system.db.commit()
        self.system.caller = adapters.invoke
        self.system.machine = {"codex": "codex.exe", "claude": "claude.exe"}
        thread = "01a14e5e-491c-7c93-872f-25d9894619d9"
        for stdout in ('{"type":"thread.started","thread_id":"%s"}\n{"type":"item.completed","item":{"type":"agent_message","text":%s}}\n{"type":"turn.completed"}'
                       % (thread, json.dumps(json.dumps({"extra": marker}))),
                       "not json " + marker):
            tid = self.submit()
            with patch.object(winproc, "run_owned", lambda *a, **k: (0, stdout, marker, 1.0)):
                self.system.tick()
            self.assertIn(self.state(tid)["state"], ("REWORK", "PAUSED_INCOMPLETE", "PAUSED_INVALID_JSON"))
            self.system.state(tid, "NEEDS_ATTENTION", "TEST_CASE_DONE")
            self.system.db.execute("UPDATE meta SET value='null' WHERE key='paused'"); self.system.db.commit()
        self.system.close(); self.system = System(self.source, self.runtime, self.fake)
        self.assertEqual(self.scan(marker), [])
        control = self.base/"scan-control.txt"
        control.write_text("control " + marker, encoding="utf-8")
        self.assertEqual(self.scan(marker), [str(control)])  # the scan itself can fail

    def test_rejected_evidence_metadata_is_bounded(self):
        marker = "FAKE-SECRET-" + uuid.uuid4().hex
        evidence = adapters.safe_evidence({"engine": "codex", "session_id": marker, "exit_code": 0,
                                           "notices": [marker], "num_turns": marker, "extra": marker})
        self.assertEqual(evidence, {"engine": "codex", "exit_code": 0})
        self.assertEqual(adapters.CallError("CLI", {"stderr": marker}).evidence, {})

    # === Defect 3: freeze re-verifies on-disk evidence at the final gate ==================
    def freeze_should_fail(self, damage):
        tid = self.accepted_and_approved()
        damage(tid, self.runtime/"tasks"/tid)
        with self.assertRaises(ValueError):
            self.freeze_version_1()
        self.assert_no_publication()

    def test_freeze_positive_control(self):
        tid = self.accepted_and_approved()
        activation = self.freeze_version_1()
        self.assertEqual(activation["dual_cli_tasks"], [tid])

    def test_freeze_rejects_modified_spec_input(self):
        def damage(tid, d):
            spec = read_json(d/"spec.json"); spec["input"] = [1, 2, 3]; write_json(d/"spec.json", spec)
        self.freeze_should_fail(damage)

    def test_freeze_rejects_deleted_spec(self):
        self.freeze_should_fail(lambda tid, d: (d/"spec.json").unlink())

    def test_freeze_rejects_corrupt_spec(self):
        self.freeze_should_fail(lambda tid, d: (d/"spec.json").write_text("{corrupt", encoding="utf-8"))

    def test_freeze_rejects_queue_record_input_change(self):
        def damage(tid, d):
            spec = json.loads(self.state(tid)["spec"]); spec["input"] = [7]
            self.system.db.execute("UPDATE tasks SET spec=? WHERE id=?", (canonical(spec).decode(), tid))
            self.system.db.commit()
        self.freeze_should_fail(damage)

    def test_freeze_rejects_replaced_artifact(self):
        def damage(tid, d):
            artifact = read_json(d/"artifact.json"); artifact["sum"] += 1; write_json(d/"artifact.json", artifact)
        self.freeze_should_fail(damage)

    def test_freeze_rejects_replaced_review(self):
        def damage(tid, d):
            review = read_json(d/"review.json"); review["review"]["binding_sha256"] = "0"*64
            write_json(d/"review.json", review)
        self.freeze_should_fail(damage)

    def test_freeze_rejects_replaced_acceptance(self):
        def damage(tid, d):
            acceptance = read_json(d/"acceptance.json"); acceptance["artifact_sha256"] = "0"*64
            write_json(d/"acceptance.json", acceptance)
        self.freeze_should_fail(damage)

    def test_freeze_rejects_replaced_attempt_evidence(self):
        def damage(tid, d):
            call = read_json(d/"writer.json")["call_id"]
            stored = read_json(d/"attempts"/call/"result.json"); stored["value"]["sum"] += 1
            write_json(d/"attempts"/call/"result.json", stored)
        self.freeze_should_fail(damage)

    def test_freeze_rejects_attempt_row_mismatch(self):
        def damage(tid, d):
            self.system.db.execute("UPDATE attempts SET session=? WHERE task=? AND stage='review'", (str(uuid.uuid4()), tid))
            self.system.db.commit()
        self.freeze_should_fail(damage)

    def test_freeze_rejects_deleted_process_record(self):
        self.freeze_should_fail(lambda tid, d: (d/"attempts"/read_json(d/"writer.json")["call_id"]/"process.json").unlink())

    def test_freeze_rejects_attempt_identity_change(self):
        def damage(tid, d):
            self.system.db.execute("UPDATE attempts SET pid=pid+4 WHERE task=? AND stage='execute'", (tid,))
            self.system.db.commit()
        self.freeze_should_fail(damage)

    def test_freeze_rejects_attempt_metadata_change(self):
        def damage(tid, d):
            self.system.db.execute("UPDATE attempts SET result=? WHERE task=? AND stage='review'", ("{}", tid))
            self.system.db.commit()
        self.freeze_should_fail(damage)

    def test_freeze_rejects_missing_budget_charge(self):
        def damage(tid, d):
            self.system.db.execute("DELETE FROM calls WHERE purpose=?", (tid + ":execute",)); self.system.db.commit()
        self.freeze_should_fail(damage)

    def test_cycle_freeze_rejects_missing_cycle_charge(self):
        self.fake_activation()
        cycle, _ = self.authorize()
        self.audit("PASS", reviewer="codex", cycle=cycle)
        tid = self.cycle_task(cycle)
        self.system.submit(tid, "analyze_numbers", [5, 2], "codex", cycle)
        self.system.tick(); self.system.tick()
        self.assertEqual(self.state(tid)["state"], "ACCEPTED")
        self.system.db.execute("DELETE FROM cycle_calls WHERE kind='review'"); self.system.db.commit()
        self.audit_evidence()
        with patch.object(deployment, "verify_repo", return_value={}):
            with self.assertRaises(ValueError):
                deployment.freeze(self.system, self.runtime/"tests.json", cycle)
        self.assertFalse((self.runtime/"snapshots").exists())

    def test_freeze_rejects_tampering_during_snapshot_copy(self):
        tid = self.accepted_and_approved()
        real, done = shutil.copyfile, []
        def copy(src, dst, *a, **k):
            if not done:
                done.append(1)
                (self.runtime/"tasks"/tid/"spec.json").write_text("{}", encoding="utf-8")
            return real(src, dst, *a, **k)
        with patch.object(deployment.shutil, "copyfile", copy):
            with self.assertRaises(ValueError):
                self.freeze_version_1()
        self.assert_no_publication()  # the staged copy is removed; nothing is activated

    # === Defect 4: audit budget exhaustion pauses consistently ============================
    def test_audit_budget_exhaustion_pauses_without_charge(self):
        self.limit(claude=20)  # an explicit local cap for the auditing engine
        for _ in range(20):
            self.system.reserve("other", engine="claude")
        with self.assertRaises(adapters.CallError) as cm:
            self.audit("PASS")
        self.assertEqual(cm.exception.kind, "BUDGET")
        self.assertEqual(self.system.meta("paused"), {"reason": "BUDGET"})
        self.assertEqual(len(self.cycle_events("AUDIT_REFUSED_PAUSE")), 1)
        self.assertEqual((self.system.calls_today(), self.cycle_events("AUDIT_ROUND_CHARGED")), (20, []))
        self.assertIsNone(self.system.meta("audit_cycle"))
        self.assertFalse((self.runtime/"independent-review").exists())
        self.assertFalse((self.runtime/"approved-review.json").exists())
        self.system.resume()  # resuming never refunds budget or audit rounds
        self.assertEqual(self.system.calls_today(), 20)
        with self.assertRaises(adapters.CallError):
            self.audit("PASS")
        self.assertEqual(self.system.calls_today(), 20)

    def test_audit_budget_pause_commits_with_its_event(self):
        self.limit(claude=20)
        for _ in range(20):
            self.system.reserve("other", engine="claude")
        original = System.event
        def crash(system, event, *a, **k):
            if event == "AUDIT_REFUSED_PAUSE":
                raise RuntimeError("simulated crash before commit")
            return original(system, event, *a, **k)
        with patch.object(System, "event", crash):
            with self.assertRaises(RuntimeError):
                self.audit("PASS")
        self.system.db.rollback()
        self.assertIsNone(self.system.meta("paused"))

    def test_concurrent_reservations_cannot_exceed_daily_limit(self):
        self.limit(codex=20)
        for _ in range(18):
            self.system.reserve("other", engine="codex")
        import threading
        barrier, outcomes = threading.Barrier(3), []
        def race():
            other = System(self.source, self.runtime, self.fake)
            try:
                barrier.wait()
                outcomes.append(other.reserve("race", engine="codex"))
            except adapters.CallError as e:
                outcomes.append(e.kind)
            finally:
                other.close()
        threads = [threading.Thread(target=race) for _ in range(3)]
        for t in threads: t.start()
        for t in threads: t.join(30)
        self.assertEqual(sorted(o == "BUDGET" for o in outcomes), [False, False, True])
        self.assertEqual(self.system.calls_today(), 20)

    def test_crashed_audit_after_reservation_is_not_refunded(self):
        with self.assertRaises(RuntimeError):
            self.audit(failure="CRASH")
        self.assertEqual((self.system.calls_today(), self.system.meta("audit_cycle")), (1, {"rounds": 1}))
        self.system.resume()
        with self.assertRaises(ValueError):
            self.audit("PASS")  # the same package cannot be re-submitted after a crash
        self.assertEqual((self.system.calls_today(), self.system.meta("audit_cycle")), (1, {"rounds": 1}))

    def test_duplicate_audit_trigger_is_serialized_without_charge(self):
        holder = subprocess.Popen([sys.executable, "-c",
            "import sys,time;sys.path.insert(0,sys.argv[1]);from researchops.core import Lock;from pathlib import Path\n"
            "with Lock(Path(sys.argv[2])):\n print('HELD',flush=True);time.sleep(4)",
            str(ROOT), str(self.runtime/"controller.lock")], stdout=subprocess.PIPE, text=True, creationflags=0x08000000)
        self.assertEqual(holder.stdout.readline().strip(), "HELD")
        with self.assertRaises(Busy):
            self.audit("PASS")
        holder.wait(20)
        self.assertEqual((self.system.calls_today(), self.system.meta("audit_cycle")), (0, None))

    # === Explicitly authorized, bounded review cycle =====================================
    def test_cycle_authorization_is_recorded_idempotent_and_exclusive(self):
        self.fake_activation()
        self.system.set_meta("audit_cycle", {"rounds": 3})
        cycle, result = self.authorize()
        self.assertTrue(result["registered"])
        record, state = self.system.cycle(cycle)
        self.assertEqual((state, record["allowed"], record["parent"]["program_audit_cycle"]),
                         ("OPEN", {"audit": 1, "execute": 1, "review": 1}, {"rounds": 3}))
        self.assertFalse(self.authorize(cycle=cycle)[1]["registered"])  # same authorization adds nothing
        self.assertEqual(len(self.cycle_events("CYCLE_AUTHORIZED")), 1)
        with self.assertRaises(ValueError):
            self.authorize(cycle=cycle, text="A different authorization text for the same cycle id.")
        with self.assertRaises(ValueError):
            self.authorize()  # one live cycle at a time
        self.assertEqual(self.system.meta("audit_cycle"), {"rounds": 3})

    def test_cycle_grants_exactly_one_audit_and_never_touches_the_exhausted_counter(self):
        self.fake_activation()
        self.system.set_meta("audit_cycle", {"rounds": 3})
        self.revise(10)
        with self.assertRaises(ValueError):
            self.audit("PASS", reviewer="codex")  # legacy path stays exhausted
        cycle, _ = self.authorize()
        with self.assertRaises(ValueError):
            self.audit("PASS", reviewer="claude", cycle=cycle)  # wrong reviewer for this cycle
        self.assertEqual(self.audit("REWORK", reviewer="codex", cycle=cycle)[0]["status"], "REWORK")
        self.assertEqual(self.system.cycle(cycle)[1], "CLOSED_REWORK")
        calls = self.system.calls_today()
        self.revise(11)
        with self.assertRaises(ValueError):
            self.audit("PASS", reviewer="codex", cycle=cycle)
        self.assertEqual(self.system.calls_today(), calls)
        self.assertEqual(self.system.meta("audit_cycle"), {"rounds": 3})

    def test_cycle_pass_admits_one_task_at_audited_source_and_activates(self):
        self.fake_activation()
        self.system.set_meta("audit_cycle", {"rounds": 3})
        cycle, _ = self.authorize()
        self.assertEqual(self.audit("PASS", reviewer="codex", cycle=cycle)[0]["status"], "PASS")
        self.assertEqual(self.system.cycle(cycle)[1], "APPROVED")
        self.revise(12)
        with self.assertRaises(ValueError):
            self.system.submit(self.cycle_task(cycle), "analyze_numbers", [1], "codex", cycle)  # other source
        self.revise(1)
        tid = self.cycle_task(cycle)
        self.system.submit(tid, "analyze_numbers", [5, 2], "codex", cycle)
        with self.assertRaises(ValueError):
            self.system.submit(tid, "analyze_numbers", [9], "codex", cycle)  # one task, fixed content
        legacy = self.submit()  # an ordinary task cannot stand in for the cycle's acceptance
        for _ in range(4):
            self.system.tick()
        self.assertEqual((self.state(tid)["state"], self.state(legacy)["state"]), ("ACCEPTED", "ACCEPTED"))
        self.assertEqual(self.system.cycle(cycle)[0]["used"], {"audit": 1, "execute": 1, "review": 1})
        self.audit_evidence()
        with patch.object(deployment, "verify_repo", return_value={}):
            activation = deployment.freeze(self.system, self.runtime/"tests.json", cycle)
        self.assertEqual((activation["dual_cli_tasks"], activation["cycle_id"]), ([tid], cycle))
        self.assertEqual(self.system.cycle(cycle)[1], "ACTIVATED")
        self.assertEqual(self.system.meta("audit_cycle"), {"rounds": 3})  # never reset or reused

    def test_cycle_task_rework_cannot_spend_beyond_the_grant(self):
        self.fake_activation()
        cycle, _ = self.authorize()
        self.audit("PASS", reviewer="codex", cycle=cycle)
        tid = self.cycle_task(cycle)
        self.system.submit(tid, "analyze_numbers", [5, 2], "codex", cycle)
        self.mutate = lambda s, v: {**v, "verdict": "REWORK", "issues": ["needs work"]} if s == "review" else v
        self.system.tick(); self.system.tick()
        calls = self.system.calls_today()
        self.system.tick()
        self.assertEqual(self.state(tid)["state"], "PAUSED_CYCLE_LIMIT")
        self.assertEqual((self.calls, self.system.calls_today()), (["codex", "claude"], calls))

    def test_cycle_freeze_rejects_forged_approval_and_foreign_tasks(self):
        self.fake_activation()
        cycle, _ = self.authorize()
        package = deployment.review_package(self.system, self.audit_evidence())
        write_json(self.runtime/"approved-review.json", {"binding_sha256": package["binding_sha256"],
                   "review": {"binding_sha256": package["binding_sha256"], "verdict": "PASS", "issues": []},
                   "cycle_id": cycle})
        self.submit(); self.system.tick(); self.system.tick()
        for target in (cycle, None):
            with patch.object(deployment, "verify_repo", return_value={}):
                with self.assertRaises((ValueError, OSError)):
                    deployment.freeze(self.system, self.runtime/"tests.json", target)
        self.assertFalse((self.runtime/"snapshots").exists())

    def test_interrupted_cycle_audit_is_closed_only_when_its_process_is_gone(self):
        self.fake_activation()
        cycle, _ = self.authorize()
        with self.assertRaises(RuntimeError):
            self.audit(failure="CRASH", reviewer="codex", cycle=cycle)
        self.assertEqual(self.system.cycle(cycle)[1], "AUDITING")
        binding = self.system.cycle(cycle)[0]["binding"]["package_binding"]
        process = self.runtime/"independent-review"/binding/"process.json"
        write_json(process, {"pid": os.getpid(), "birth": winproc.identity(os.getpid())})
        with self.assertRaises(ValueError):
            self.authorize()  # its process is still alive
        write_json(process, {"pid": os.getpid(), "birth": "different-birth"})
        text = "A second, separately worded authorization for the replacement cycle."
        new_cycle, _ = self.authorize(text=text)
        old = self.system.cycle(cycle)
        self.assertEqual((old[1], old[0]["used"]["audit"]), ("CLOSED_AMBIGUOUS", 1))
        new = self.system.cycle(new_cycle)
        self.assertEqual((new[1], new[0]["cycle_id"], new[0]["authorization"]["text"], new[0]["used"], new[0]["binding"]),
                         ("OPEN", new_cycle, text, {"audit": 0, "execute": 0, "review": 0}, None))
        self.revise(50); self.assertEqual(self.audit("REWORK", reviewer="codex", cycle=new_cycle)[0]["status"], "REWORK")
        self.revise(51)
        with self.assertRaises(ValueError): self.audit("PASS", reviewer="codex", cycle=new_cycle)

    def test_unusable_approved_cycle_can_be_closed_without_refund(self):
        self.fake_activation()
        cycle, _ = self.authorize()
        self.audit("PASS", reviewer="codex", cycle=cycle)
        tid = self.cycle_task(cycle)
        self.system.submit(tid, "analyze_numbers", [5, 2], "codex", cycle)
        self.mutate = lambda s, v: {**v, "verdict": "REWORK", "issues": ["needs work"]} if s == "review" else v
        for _ in range(3): self.system.tick()
        self.assertEqual(self.state(tid)["state"], "PAUSED_CYCLE_LIMIT")
        with self.assertRaises(ValueError): self.authorize()  # the approved cycle still blocks
        call = self.system.db.execute("SELECT call FROM cycle_calls WHERE kind='execute'").fetchone()[0]
        self.system.db.execute("UPDATE attempts SET pid=?,birth=? WHERE id=?",
                               (os.getpid(), winproc.identity(os.getpid()), call)); self.system.db.commit()
        with self.assertRaises(ValueError): deployment.close_cycle(self.system, cycle, "Acceptance task cannot finish.")
        self.system.db.execute("UPDATE attempts SET pid=?,birth=? WHERE id=?", (self.dead_child, "1", call))
        self.system.db.commit()
        closed = deployment.close_cycle(self.system, cycle, "Acceptance task cannot finish.")
        self.assertEqual((closed["state"], closed["used"]), ("CLOSED_BY_OPERATOR", {"audit": 1, "execute": 1, "review": 1}))
        with self.assertRaises(ValueError): deployment.close_cycle(self.system, cycle, "Closing a second time.")
        self.assertEqual(self.authorize(text="A fresh authorization after closure.")[1]["state"], "OPEN")

    def test_command_has_enforced_tool_controls(self):
        schema = self.runtime/"command-schema.json"
        write_json(schema, {"type": "object", "properties": {}, "additionalProperties": False})
        cmd = adapters.command("claude", {"claude": "cli.exe"}, str(uuid.uuid4()), schema)
        self.assertEqual(cmd[cmd.index("--tools")+1], "")
        self.assertIn("--safe-mode", cmd)
        self.assertIn("--strict-mcp-config", cmd)
        self.assertIn("dontAsk", cmd)
        self.assertEqual(json.loads(cmd[cmd.index("--json-schema")+1]), read_json(schema))
        cmd = adapters.command("codex", {"codex": "cli.exe"}, "unused", "schema")
        self.assertIn("read-only", cmd)
        self.assertIn("--ignore-user-config", cmd)
        self.assertIn("shell_tool", cmd)
        for feature in ("computer_use", "image_generation", "hooks", "skill_search", "view_image"):
            self.assertIn(feature, cmd)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", cmd)

    def test_codex_tool_event_rejected(self):
        raw = '\n'.join(json.dumps(e) for e in [
            {"type": "thread.started", "thread_id": "test"},
            {"type": "item.started", "item": {"type": "command_execution"}}])
        with self.assertRaises(adapters.CallError): adapters.parse("codex", raw, "test")

    def test_unknown_codex_tool_event_fails_closed(self):
        raw = json.dumps({"type": "item.completed", "item": {"type": "future_computer_tool"}})
        with self.assertRaises(adapters.CallError): adapters.parse("codex", raw, "test")

    def test_exact_disabled_host_notice_is_not_a_tool_call(self):
        raw = '\n'.join(json.dumps(e) for e in [
            {"type": "thread.started", "thread_id": "01a14e5e-491c-7c93-872f-25d9894619d9"},
            {"type": "item.completed", "item": {"type": "error", "message": adapters.CODE_MODE_DISABLED_NOTICE}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": '{"answer":2}'}},
            {"type": "turn.completed"}])
        value, evidence = adapters.parse("codex", raw, "unused")
        self.assertEqual(value, {"answer": 2})
        self.assertEqual(evidence["notices"], ["CODE_MODE_HOST_DISABLED"])

    def test_other_codex_error_item_is_rejected(self):
        raw = json.dumps({"type": "item.completed", "item": {"type": "error", "message": "authentication failed"}})
        with self.assertRaises(adapters.CallError) as cm: adapters.parse("codex", raw, "test")
        self.assertEqual(cm.exception.kind, "AUTH")

    def test_status_read_does_not_require_dispatch_lock(self):
        self.submit()
        with self.system.lock():
            report = self.system.report(persist=False)
        self.assertEqual(report["tasks"][0]["state"], "QUEUED")

    def test_claude_session_mismatch_rejected(self):
        with self.assertRaises(adapters.CallError):
            adapters.parse("claude", json.dumps({"session_id": "other", "result": "{}"}), "wanted")

    def test_error_classification(self):
        self.assertEqual(adapters.classify("401 Unauthorized"), "AUTH")
        self.assertEqual(adapters.classify("quota exceeded"), "QUOTA")
        self.assertEqual(adapters.classify("DNS connection failed"), "NETWORK")


@unittest.skipUnless(os.name == "nt", "Windows only")
class ProcessTests(unittest.TestCase):
    def test_real_owned_process_timeout_leaves_unrelated_process_alive(self):
        seen = []
        rc, out, err, seconds = winproc.run_owned(
            [sys.executable, "-c", "import time;time.sleep(30)"], "", ROOT,
            os.environ.copy(), 0.2, lambda pid, birth: seen.append((pid, birth)), 256)
        self.assertEqual(rc, 1460)
        self.assertIsNone(winproc.identity(seen[0][0]))
        self.assertIsNotNone(winproc.identity(os.getpid()))

    def test_real_owned_child_can_succeed(self):
        rc, out, err, seconds = winproc.run_owned(
            [sys.executable, "-c", "print('OK')"], "", ROOT, os.environ.copy(),
            5, lambda pid, birth: self.assertTrue(birth and birth != "UNKNOWN"), 256)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "OK")

    def test_scheduler_policy_source(self):
        text = (ROOT/"tools/schedule.ps1").read_text(encoding="utf-8")
        for required in ("-LogonType Interactive", "-RunLevel Limited", "-Hidden", "-StartWhenAvailable",
                         "-MultipleInstances IgnoreNew", "WakeToRun = $false", "-Minutes 15", "Assert-Owned",
                         "ValidateSet('Install','Inspect','Uninstall','Disable','Enable')", "if ($existing) { Assert-Owned $existing }"):
            self.assertIn(required, text)
        for forbidden in ("Stop-Process", "Stop-ScheduledTask", "-Password", "-UserId SYSTEM", "-Force"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()

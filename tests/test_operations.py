"""Inactive candidate tests: in-memory DB and isolated runtime, no live SSH/models."""
import datetime as dt
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]
IS_CANDIDATE = BASE.name == "operations-candidate"
REPO = BASE.parents[2] if IS_CANDIDATE else BASE
sys.path.insert(0, str(REPO))
if IS_CANDIDATE:
    # Isolated import namespace avoids mutating production researchops module objects.
    package = types.ModuleType("operations_candidate_fixture")
    package.__path__ = [str(BASE / "researchops"), str(REPO / "researchops")]
    sys.modules[package.__name__] = package
    for name in ("evidence", "reporting", "operations"):
        spec = importlib.util.spec_from_file_location(package.__name__ + "." + name, BASE / "researchops" / (name + ".py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        setattr(package, name, module)
        spec.loader.exec_module(module)
    evidence, op, reporting = package.evidence, package.operations, package.reporting
else:
    from researchops import evidence, operations as op, reporting


class FakeSystem:
    def __init__(self, root):
        self.root = root
        self.runtime = root / ".runtime"
        self.runtime.mkdir()
        self.policy = {"daily_review_limit": 50, "engine_daily_limits": {"codex": None, "claude": None}}
        self.db = sqlite3.connect(":memory:")
        self.db.executescript("CREATE TABLE calls(id,day,purpose,created); CREATE TABLE call_engines(call,engine,task,stage); CREATE TABLE tasks(id,spec,state,created);")
    @property
    def lock(self):
        raise AssertionError("Nested System.lock forbidden")
    def report(self, *args, **kwargs):
        raise AssertionError("Recursive System.report forbidden")


class OperationsTests(unittest.TestCase):
    def setUp(self):
        parent = REPO / ".runtime" / "operations-unit-tests"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.root = Path(self.temp.name)
        (self.root / "README.md").write_text("fixture source\n")
        self.system = FakeSystem(self.root)
        self.cards = []
        self.card_patch = patch.object(op.projects, "status_cards", side_effect=lambda system, **kwargs: self.cards)
        self.card_patch.start()
        self.clock = patch.object(op, "_now", return_value=dt.datetime(2026, 10, 18, 22, tzinfo=dt.timezone.utc))
        self.clock.start()
    def tearDown(self):
        self.card_patch.stop(); self.clock.stop(); self.system.db.close(); self.temp.cleanup()
    def cfg(self, enabled=False):
        cfg = {"schema": 1, "enabled": enabled}
        if enabled:
            cfg.update(host_alias="ApprovedHost", read_root="/cephfs/approved/research", known_files=[], monitor_scripts=[], cadence_seconds=900)
        (self.system.runtime / "research-watch.json").write_text(json.dumps(cfg))
    def observation(self, changed=True):
        return {"transport": "OK", "reason": "STATIC_READONLY_PROBE", "read_only": True, "model_calls": 0, "actions_dispatched": 0,
                "fingerprint": "a" * 64, "changed": changed, "processes": [{"state": "LIVE"}],
                "ssh_metadata": {"hostname": ["PRIVATE_IP"]}, "host": "PRIVATE_HOST", "argv": "SECRET_ARGS"}
    def read_report(self, result):
        path = self.system.runtime / result["output_relative"]
        return path, json.loads((path / "index.json").read_text())
    def test_disabled_default_calls_final_api_without_helpers(self):
        with patch.object(op.research_observer.winproc, "run_owned", side_effect=AssertionError("SSH forbidden")):
            result = op.refresh_watch(self.system)
        self.assertFalse(result["enabled"]); self.assertEqual(result["reason"], "OBSERVER_DISABLED")
        self.assertEqual(result["summary"]["transport"], "DISABLED")
    def test_cadence_exactly_900_seconds_and_changed_flag(self):
        self.cfg(True)
        with patch.object(op.time, "time", side_effect=[1000, 1899, 1900]), patch.object(op.research_observer, "observe", return_value=self.observation()) as observe:
            self.assertTrue(op.refresh_watch(self.system)["changed"])
            self.assertFalse(op.refresh_watch(self.system)["changed"])
            self.assertTrue(op.refresh_watch(self.system)["refreshed"])
            self.assertEqual(observe.call_count, 2)
            self.assertEqual(observe.call_args.args, (self.system.runtime,))
    def test_source_and_config_change_refresh_before_cadence(self):
        with patch.object(op.time, "time", return_value=1000), patch.object(op.research_observer, "observe", return_value=self.observation(False)) as observe:
            op.refresh_watch(self.system)
            (self.root / "README.md").write_text("changed source\n")
            op.refresh_watch(self.system)
            self.cfg(False)
            op.refresh_watch(self.system)
            self.assertEqual(observe.call_count, 3)
    def test_force_refresh_and_clock_rollback_do_not_dispatch(self):
        with patch.object(op.time, "time", side_effect=[1000, 900, 900]), patch.object(op.research_observer, "observe", return_value=self.observation(False)) as observe:
            op.refresh_watch(self.system)
            self.assertFalse(op.refresh_watch(self.system)["refreshed"])
            self.assertTrue(op.refresh_watch(self.system, force=True)["refreshed"])
            self.assertEqual(observe.call_count, 2)
    def test_crash_start_marker_prevents_hot_retry(self):
        with patch.object(op.time, "time", return_value=1000), patch.object(op.research_observer, "observe", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt): op.refresh_watch(self.system)
        with patch.object(op.time, "time", return_value=1001), patch.object(op.research_observer, "observe", side_effect=AssertionError("repeat")):
            self.assertEqual(op.refresh_watch(self.system)["previous_state"], "STARTED")
    def test_failed_observer_is_bounded_and_raw_exception_is_not_saved(self):
        with patch.object(op.time, "time", return_value=1000), patch.object(op.research_observer, "observe", side_effect=RuntimeError("SECRET")) as observe:
            self.assertEqual(op.refresh_watch(self.system)["state"], "FAILED")
            self.assertFalse(op.refresh_watch(self.system)["refreshed"])
            self.assertEqual(observe.call_count, 1)
        self.assertNotIn("SECRET", (self.system.runtime / "operations/watch-state.json").read_text())
    def test_invalid_config_never_calls_observer(self):
        (self.system.runtime / "research-watch.json").write_text('{"schema":1,"enabled":false,"raw_command":"danger"}')
        with patch.object(op.research_observer, "observe") as observe:
            with self.assertRaises(ValueError): op.refresh_watch(self.system)
            observe.assert_not_called()
    def test_daily_immutable_unchanged_refresh_and_utc(self):
        first = op.refresh_daily(self.system)
        second = op.refresh_daily(self.system)
        self.assertTrue(first["refreshed"]); self.assertFalse(second["refreshed"])
        self.assertEqual(first["output_relative"], second["output_relative"])
        path, data = self.read_report(first)
        self.assertIn("2026-10-18 (UTC)", (path / "REPORT.md").read_text(encoding="utf-8"))
        self.assertFalse(data["publish"]); self.assertEqual(data["images"][0]["status"], "MISSING")
        self.assertEqual(data["tasks"], [])
        forced = op.refresh_daily(self.system, force=True)
        self.assertNotEqual(first["output_relative"], forced["output_relative"])
        self.assertTrue(path.is_dir())
    def test_real_sql_budget_keeps_old_reviews_and_unknown_provider_quota(self):
        self.system.db.executemany("INSERT INTO calls VALUES(?,?,?,?)", [("old", "2026-10-18", "independent-review:old", "t"), ("new", "2026-10-18", "tid:execute", "t"), ("past", "2026-10-17", "independent-review:past", "t")])
        self.system.db.execute("INSERT INTO call_engines VALUES('new','codex','tid','execute')")
        before = self.system.db.total_changes
        result = op.refresh_daily(self.system)
        self.assertEqual(self.system.db.total_changes, before)
        _, data = self.read_report(result)
        self.assertEqual(data["models"]["review_used"], 1)
        self.assertEqual(data["models"]["engine_calls"], {"codex": 1, "claude": 0})
        self.assertEqual(data["models"]["provider_quota"], "UNKNOWN")
    def test_operational_acceptance_never_becomes_scientific_ready(self):
        self.cards = [{"project_id": "project-1", "profile": "factory", "kind": "ops-smoke", "state": "ACCEPTED", "blocking_reason": None, "active_goal": "goal-1", "output_root": "SECRET_LOCAL_PATH", "tasks": [{"id": "task-1", "state": "ACCEPTED", "reason": None, "evidence": "SECRET_EVIDENCE_PATH", "content_binding": {"evidence_state": "VERIFIED_ACCEPTANCE"}}]}]
        result = op.refresh_daily(self.system); path, data = self.read_report(result)
        p = data["operations"]["projects"][0]
        self.assertEqual(p["state"], "ACCEPTED"); self.assertEqual(p["scientific_status"], "UNVERIFIED")
        self.assertEqual(p["tasks"][0]["scientific_status"], "UNVERIFIED")
        self.assertNotIn("SECRET", (path / "index.json").read_text())
        self.assertEqual(data["tasks"], [])
    def test_observer_sanitized_and_changes_refresh_daily(self):
        with patch.object(op.research_observer, "observe", return_value=self.observation()): op.refresh_watch(self.system)
        first = op.refresh_daily(self.system); path, data = self.read_report(first)
        self.assertNotIn("PRIVATE", (path / "index.json").read_text())
        self.assertNotIn("SECRET", (path / "index.json").read_text())
        self.assertEqual(data["operations"]["observer"]["process_counts"]["LIVE"], 1)
        self.cards = [{"project_id": "p1", "profile": "factory", "kind": "research", "state": "ACTIVE", "tasks": []}]
        self.assertTrue(op.refresh_daily(self.system)["refreshed"])
    def test_corrupt_report_or_extra_file_rebuilds_without_overwrite(self):
        first = op.refresh_daily(self.system); path, _ = self.read_report(first)
        (path / "EXTRA.txt").write_text("unlisted")
        second = op.refresh_daily(self.system)
        self.assertTrue(second["refreshed"]); self.assertNotEqual(first["output_relative"], second["output_relative"])
        self.assertTrue((path / "EXTRA.txt").exists())
        p2, _ = self.read_report(second); (p2 / "REPORT.md").write_text("corrupted")
        self.assertTrue(op.refresh_daily(self.system)["refreshed"])
    def test_changed_budget_and_source_refresh_daily(self):
        op.refresh_daily(self.system)
        self.system.db.execute("INSERT INTO calls VALUES('x','2026-10-18','cycle-review:x','t')")
        self.assertTrue(op.refresh_daily(self.system)["refreshed"])
        (self.root / "README.md").write_text("new\n")
        self.assertTrue(op.refresh_daily(self.system)["refreshed"])
    def test_raw_or_forged_operational_summary_rejected(self):
        with self.assertRaises(evidence.EvidenceError): reporting._operations({"hidden_reasoning": "not accepted"})
        summary = {"schema": 1, "projects": [], "observer": op.safe_observer(None), "operational_tasks_are_scientific_evidence": True}
        with self.assertRaises(evidence.EvidenceError): reporting._operations(summary)
    def test_stale_retained_static_does_not_keep_an_accepted_scientific_claim(self):
        tid = "a7b3eccb-2e47-4f76-8e2f-5377cebd9741"
        self.system.db.execute("INSERT INTO tasks VALUES(?,?,?,?)", (tid, json.dumps({"action": "scene_stair_workflow"}), "ACCEPTED", "t"))
        with patch.object(evidence, "accepted_static_reference", side_effect=evidence.EvidenceError("STALE_FILE_HASH")):
            result = op.refresh_daily(self.system, verify_science=True)
        _, data = self.read_report(result)
        assessment = data["tasks"][0]["assessment"]
        self.assertEqual(assessment["status"], "UNVERIFIED")
        self.assertEqual(assessment["layers"]["STATIC_GEOMETRY"]["reason"], "RETAINED_STATIC_RECHECK_FAILED")
    def test_unsafe_state_path_reparse_rejected(self):
        outside = self.root / "outside"; outside.mkdir()
        link = self.system.runtime / "operations"
        # Windows junction creation uses native PowerShell? Avoid shell mutation in unit.
        # Patch the primitive to prove unsafe paths cannot reach write_json.
        with patch.object(evidence.EvidenceStore, "_no_links", side_effect=evidence.EvidenceError("UNSAFE_REPARSE_PATH")):
            with self.assertRaises(evidence.EvidenceError): op.refresh_daily(self.system)

    def test_stop_signal_survives_daily_sanitization_without_paths_or_raw_log(self):
        raw={"transport":"OK","known_files":[{"path":"/private/location/stop.json",
              "progress":{"signals":["ENTIRE_TASK_STOP_REQUIRED","token=not-a-signal"]}}]}
        summary=op.safe_observer(raw)
        self.assertEqual(summary["progress_signals"],["ENTIRE_TASK_STOP_REQUIRED"])
        self.assertNotIn("private",json.dumps(summary))
        self.assertNotIn("token",json.dumps(summary))


if __name__ == "__main__": unittest.main()

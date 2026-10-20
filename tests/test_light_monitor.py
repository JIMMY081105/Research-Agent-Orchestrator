"""Light monitoring must defer science; explicit deep checks remain fail-capable.

Only tiny synthetic fixtures and memory SQLite are used. No tools/models/network.
"""
import contextlib
import copy
import datetime as dt
import importlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import uuid

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
IS_CANDIDATE = HERE.name == "agent-monitor-fix"
REPO = HERE.parents[2] if IS_CANDIDATE else HERE.parent
sys.path.insert(0, str(REPO))
if IS_CANDIDATE:
    package = types.ModuleType("light_monitor_candidate_fixture")
    package.__path__ = [str(HERE/"researchops"), str(REPO/"researchops")]
    sys.modules[package.__name__] = package
    modules = {name: importlib.import_module(package.__name__+"."+name)
               for name in ("evidence", "projects", "operations", "core", "science", "deployment", "integrity")}
else:
    modules = {name: importlib.import_module("researchops."+name)
               for name in ("evidence", "projects", "operations", "core", "science", "deployment", "integrity")}
evidence, projects, op, core, science, deployment, integrity = (modules[name] for name in
    ("evidence", "projects", "operations", "core", "science", "deployment", "integrity"))


class FakeSystem:
    def __init__(self, directory):
        self.root = directory/"source"; self.root.mkdir()
        (self.root/"README.md").write_text("Tiny source fixture.\n", encoding="utf-8")
        self.runtime = directory/"runtime"; self.runtime.mkdir()
        self.policy = {"daily_review_limit": 50, "engine_daily_limits": {"codex": None, "claude": None},
                       "mode": "observe-analysis-and-cpu-scene-workflows", "actions": ["analyze_text"]}
        self.db = sqlite3.connect(":memory:"); self.db.row_factory = sqlite3.Row
        self.db.executescript("CREATE TABLE tasks(id,spec,state,reason,reworks,created,updated);"
            "CREATE TABLE calls(id,day,purpose,created); CREATE TABLE call_engines(call,engine,task,stage);"
            "CREATE TABLE review_cycles(id,task,state,created);")
    def meta(self, key): return None
    def calls_today(self): return 0
    def reviews_today(self): return 0
    def engine_paused(self, engine): return None
    def report(self, *args, **kwargs): raise AssertionError("Nested report")
    def call(self, *args, **kwargs): raise AssertionError("Model call")
    def submit(self, *args, **kwargs): raise AssertionError("Task submission")


class LightMonitorTests(unittest.TestCase):
    def setUp(self):
        parent = REPO/".runtime/tests/light-monitor"; parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.system = FakeSystem(Path(self.temp.name)); self.store = evidence.EvidenceStore(self.system.runtime)
        self.tid = str(uuid.uuid4()); self.pid = str(uuid.uuid4()); self.gid = str(uuid.uuid4())
        self.project_dir = self.system.runtime/"projects"/self.pid; self.project_dir.mkdir(parents=True)
        self.project = {"id": self.pid, "name": "Tiny historical fixture", "profile": "factory", "kind": "research",
            "active_goal": self.gid, "rules_sha256": "c"*64, "output_root": str(self.project_dir/"outputs")}
        self.goal = {"id": self.gid, "goal_sha256": "d"*64,
                     "plan": [{"id": self.tid, "action": "scene_stair_workflow"}]}
        self.clock = patch.object(op, "_now", return_value=dt.datetime(2026,10,19,0,0,tzinfo=dt.timezone.utc)); self.clock.start()
    def tearDown(self):
        self.clock.stop(); self.system.db.close(); self.temp.cleanup()
    def write(self, relative, value):
        path = self.store.path(relative); path.parent.mkdir(parents=True,exist_ok=True)
        if isinstance(value, bytes): path.write_bytes(value)
        else: integrity.write_json(path,value)
        return path
    def row(self, tid, spec, state="ACCEPTED"):
        self.system.db.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?)",(tid,json.dumps(spec),state,None,0,"t","t"))
    def legacy(self):
        source_bytes = b"# tiny static checker fixture\n"
        source_files = {"checker.py": integrity.digest(source_bytes)}
        sha = integrity.digest(integrity.canonical(source_files)); data = {"unit_fixture": True}
        self.spec = {"id":self.tid,"action":"scene_stair_workflow","input":data,
            "input_sha256":integrity.digest(integrity.canonical(data)),"source":{"sha256":sha,"files":source_files},
            "project_binding":{"project_id":self.pid,"goal_id":self.gid}}
        self.write("snapshots/"+sha+"/source/checker.py",source_bytes)
        tools = ("scene.room_meshes","stair.candidates","stair.build_usd","stair.check_usd")
        runs = []
        for tool in tools:
            name = "exec-fixture/"+tool+"/"+("stair.usda" if tool=="stair.build_usd" else "result.json")
            path=self.write("tasks/"+self.tid+"/work/"+name,b"tiny unit fixture only\n")
            runs.append({"tool":tool,"ok":True,"exit_code":0,"outputs":{name:integrity.digest(path.read_bytes())}})
        artifact={"task_id":self.tid,"input_sha256":self.spec["input_sha256"],"source_sha256":sha,
                  "checks":{"unit_fixture_geometry":True},"tool_runs":runs}
        binding=integrity.digest(integrity.canonical({"spec":self.spec,"artifact":artifact})); call=str(uuid.uuid4())
        acceptance={"source_sha256":sha,"artifact_sha256":integrity.digest(integrity.canonical(artifact)),
                    "binding_sha256":binding,"review_call":call,"accepted_at":"2026-10-18T12:00:00+00:00"}
        prefix="tasks/"+self.tid+"/"
        for name,value in (("spec",self.spec),("artifact",artifact),("acceptance",acceptance),
            ("writer",{"engine":"codex","evidence":{"exit_code":0}}),
            ("review",{"review":{"task_id":self.tid,"binding_sha256":binding,"verdict":"PASS","issues":[]},
                       "call_id":call,"evidence":{"engine":"claude","exit_code":0}})):
            self.write(prefix+name+".json",value)
        self.row(self.tid,self.spec)
        return artifact
    def index(self, report):
        relative="science-runs/"+str(uuid.uuid4())+"/report.json"; self.write(relative,report)
        ref=self.store.fingerprint(relative)
        self.write("science-index.json",{self.tid:ref.as_dict()}); return ref
    @contextlib.contextmanager
    def governance(self):
        with patch.object(projects,"get_project",return_value=copy.deepcopy(self.project)), \
             patch.object(projects,"get_goal",return_value=copy.deepcopy(self.goal)), \
             patch.object(projects,"binding_for_submission",return_value={}), \
             patch.object(projects,"binding_current",return_value=True):
            yield
    @contextlib.contextmanager
    def no_heavy(self):
        with patch.object(evidence,"accepted_static_reference",side_effect=AssertionError("Deep static rehash")), \
             patch.object(science,"reconstruct_assessment",side_effect=AssertionError("Deep science reconstruction")), \
             patch.object(science.appcontainer,"hash_tree",side_effect=AssertionError("Runtime tree rehash")), \
             patch.object(deployment,"verified_acceptance",side_effect=AssertionError("Accepted proof recheck")):
            yield
    def scientific(self, tasks): return tasks[0]["assessment"]["layers"]["STATIC_GEOMETRY"]
    def test_routine_retained_science_never_calls_deep_or_trusts_ready_json(self):
        self.legacy(); self.index({"status":"READY","passed":True,"process_verified":True,"assessment":{"status":"READY"}})
        with self.no_heavy(): rows=op._retained_science(self.system,self.store)
        static=self.scientific(rows)
        self.assertEqual((static["status"],static["reason"]),("UNVERIFIED","SCIENTIFIC_REVALIDATION_DEFERRED"))
        self.assertNotIn("legacy_static_accepted",static)
        self.assertEqual(rows[0]["assessment"]["status"],"UNVERIFIED")
    def test_routine_does_not_parse_control_report_or_open_assets(self):
        self.legacy(); self.index(b"not valid JSON; READY is only untrusted historical text")
        original_text=Path.read_text; original_bytes=Path.read_bytes
        def text(path,*args,**kwargs):
            if path.name in ("artifact.json","report.json") or "_sandbox" in path.parts or "work" in path.parts:
                raise AssertionError("Raw evidence read by routine")
            return original_text(path,*args,**kwargs)
        def raw(path,*args,**kwargs):
            if "_sandbox" in path.parts or "work" in path.parts or path.name=="artifact.json":
                raise AssertionError("Asset read by routine")
            return original_bytes(path,*args,**kwargs)
        with self.no_heavy(),patch.object(Path,"read_text",text),patch.object(Path,"read_bytes",raw):
            rows=op._retained_science(self.system,self.store)
        self.assertEqual(self.scientific(rows)["reason"],"SCIENTIFIC_REVALIDATION_DEFERRED")
    def test_oversized_anchor_rejected_before_fingerprint(self):
        self.legacy(); ref=self.index(b"small history")
        with self.store.path(ref.path).open("wb") as stream: stream.seek(op.MAX_HISTORY_BYTES);stream.write(b"x")
        original=evidence.EvidenceStore.fingerprint; attempted=[]
        def bounded(store,relative):
            if store.path(relative).is_file() and store.path(relative).stat().st_size>op.MAX_HISTORY_BYTES:
                attempted.append(relative);raise AssertionError("Oversized metadata hashed")
            return original(store,relative)
        with self.no_heavy(),patch.object(evidence.EvidenceStore,"fingerprint",bounded):
            rows=op._retained_science(self.system,self.store)
        self.assertEqual(attempted,[]);self.assertEqual(self.scientific(rows)["status"],"UNVERIFIED")
        self.assertIn("DEFERRED",self.scientific(rows)["reason"])
    def test_malformed_or_sensitive_control_index_does_not_mint_ready(self):
        self.legacy()
        for item in ({"path":"../outside/report.json","sha256":"a"*64},
                     {"path":"machine.json","sha256":"a"*64}, {"path":"science-runs/invalid/report.json","sha256":"a"*64}):
            self.write("science-index.json",{self.tid:item})
            with self.no_heavy(): rows=op._retained_science(self.system,self.store)
            self.assertEqual(self.scientific(rows)["status"],"UNVERIFIED")
            self.assertNotEqual(self.scientific(rows)["reason"],"SCIENTIFIC_REVALIDATION_DEFERRED")
    def test_light_project_status_never_rechecks_artifact_or_acceptance(self):
        self.legacy()
        original=projects._read
        def read(path):
            if Path(path).name=="artifact.json":raise AssertionError("Artifact opened for display")
            return original(path)
        with self.governance(),self.no_heavy(),patch.object(projects,"_read",read):
            cards=projects.status_cards(self.system,verify_evidence=False)
        self.assertEqual(cards[0]["state"],"UNVERIFIED")
        self.assertEqual(cards[0]["blocking_reason"],"EVIDENCE_RECHECK_DEFERRED")
        binding=cards[0]["tasks"][0]["content_binding"]
        self.assertEqual(binding["evidence_state"],"EVIDENCE_RECHECK_DEFERRED");self.assertIsNone(binding["artifact_sha256"])
    def test_strict_project_status_default_still_rejects_tampered_acceptance(self):
        self.legacy()
        with self.governance(),patch.object(deployment,"verified_acceptance",side_effect=ValueError("Tampered fixture")) as verify:
            cards=projects.status_cards(self.system)
        verify.assert_called_once();self.assertEqual(cards[0]["state"],"BLOCKED")
        self.assertEqual(cards[0]["tasks"][0]["content_binding"]["evidence_state"],"INVALID_EVIDENCE")
    def test_system_report_explicitly_uses_light_status(self):
        self.legacy()
        with self.no_heavy(),patch.object(projects,"status_cards",return_value=[]) as cards:
            value=core.System.report(self.system,persist=False)
        cards.assert_called_once_with(self.system,verify_evidence=False)
        self.assertEqual(value["projects"],[])
    def test_routine_daily_and_unchanged_reuse_do_not_reconstruct_science(self):
        self.legacy();self.index({"status":"READY","passed":True})
        with self.no_heavy(),patch.object(projects,"status_cards",return_value=[]) as cards:
            first=op.refresh_daily(self.system);second=op.refresh_daily(self.system)
        self.assertTrue(first["refreshed"]);self.assertFalse(second["refreshed"])
        for call in cards.call_args_list:self.assertEqual(call.kwargs,{"verify_evidence":False})
        index=json.loads((self.system.runtime/first["output_relative"]/"index.json").read_text())
        self.assertEqual(index["tasks"][0]["assessment"]["status"],"UNVERIFIED")
        self.assertEqual(self.scientific(index["tasks"])["reason"],"SCIENTIFIC_REVALIDATION_DEFERRED")
    def test_deep_daily_explicitly_requests_strict_status(self):
        with patch.object(projects,"status_cards",return_value=[]) as cards:
            op.refresh_daily(self.system,verify_science=True)
        cards.assert_called_once_with(self.system,verify_evidence=True)
    def test_deep_static_rechecks_real_tiny_hashes_and_rejects_changed_asset(self):
        artifact=self.legacy()
        rows=op._retained_science(self.system,self.store,verify_science=True)
        self.assertTrue(self.scientific(rows).get("legacy_static_accepted"))
        output=artifact["tool_runs"][2]["outputs"]
        relative=next(iter(output));self.store.path("tasks/"+self.tid+"/work/"+relative).write_bytes(b"tampered tiny fixture")
        rows=op._retained_science(self.system,self.store,verify_science=True)
        self.assertEqual((self.scientific(rows)["status"],self.scientific(rows)["reason"]),
                         ("UNVERIFIED","RETAINED_STATIC_RECHECK_FAILED"))
        self.assertNotIn("legacy_static_accepted",self.scientific(rows))
    def test_failed_current_control_reconstruction_cannot_leave_legacy_static(self):
        self.legacy();self.index({"status":"PASS","passed":True})
        with patch.object(science,"reconstruct_assessment",side_effect=evidence.EvidenceError("STALE_EXECUTION_SANDBOX")) as reconstruction:
            rows=op._retained_science(self.system,self.store,verify_science=True)
        reconstruction.assert_called_once()
        self.assertEqual(self.scientific(rows)["reason"],"RETAINED_STATIC_RECHECK_FAILED")
        self.assertNotIn("legacy_static_accepted",self.scientific(rows))
    def test_nonboolean_flags_are_rejected_without_heavy_work(self):
        with self.no_heavy():
            with self.assertRaises(ValueError):op.refresh_daily(self.system,verify_science=1)
            with self.assertRaises(ValueError):projects.status_cards(self.system,verify_evidence="false")


if __name__=="__main__":unittest.main()

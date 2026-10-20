"""CLI governance boundaries use temporary state and explicitly fake model outputs."""
import contextlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / "researchops.py").is_file():
    ROOT = Path(r"E:\Github\Building-Generation-Validation")
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
import test_system as baseline
from researchops import projects
from researchops.integrity import canonical, digest, read_json, write_json

_spec = importlib.util.spec_from_file_location("governance_cli_under_test", ROOT / "researchops.py")
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)


class GovernanceCLITests(unittest.TestCase):
    setUp = baseline.QueueTests.setUp
    tearDown = baseline.QueueTests.tearDown

    def fake(self, engine, machine, policy, prompt, schema, cwd, on_start, session):
        # The actual System.call writes the attempt, session, result and ledger. No CLI runs.
        self.calls.append(engine)
        self.assertEqual(engine, "claude")
        on_start(self.dead_child, "1")
        package = read_json(Path(cwd) / "request.json")
        slots = package["task_slots"]
        input_id = next(iter(package["request"]["inputs"]))
        kind = package["request"]["inputs"][input_id]["kind"]
        action = "analyze_text" if kind == "text" else "analyze_numbers"
        tasks = [{"id": slots[n], "action": action, "input_id": input_id,
                  "question": "Summarize only the supplied literal material." if kind == "text" else "",
                  "depends_on": []} for n in range(getattr(self, "leaf_count", 1))]
        value = {"binding_sha256": digest(canonical(package)), "status": "PLANNED", "issues": [], "tasks": tasks}
        return value, {"engine": engine, "exit_code": 0, "requested_session_id": session,
                       "session_id": session, "tools_disabled": True}

    def planned(self, large=False):
        project, proposal, goal = (str(uuid.uuid4()) for _ in range(3))
        projects.register_project(self.system, project, "CLI controlled fixture", "office",
            "Use supplied literal material only; no research writes, GPU or publication.",
            ["analyze_numbers", "analyze_text"], kind="ops-smoke")
        request = {"goal_id": goal, "prompt": "Compute or summarize the supplied literal material, preserving its limits.",
                   "inputs": {"material": {"kind": "text" if large else "numbers",
                                           "value": "Literal material. " * 850 if large else [2, 3, 7]}}}
        path = self.base / "request.json"
        write_json(path, request)
        self.leaf_count = 3 if large else 1
        result = cli.governance_command(self.system,
            SimpleNamespace(cmd="goal-plan", project=project, id=proposal, file=path))
        self.assertEqual(result["status"], "PLANNED")
        self.assertFalse(result["approved"])
        self.assertEqual(self.system.reviews_today(), 1)
        self.assertEqual(self.system.db.execute("SELECT count(*) FROM tasks").fetchone()[0], 0)
        folder = self.runtime / "projects" / project / "proposals" / proposal
        return project, proposal, goal, result, folder

    def adopt(self, project, proposal):
        return cli.governance_command(self.system, SimpleNamespace(cmd="goal-adopt", project=project, proposal=proposal))

    def test_cli_rules_update_invalidates_previously_planned_proposal(self):
        project, proposal, _, _, _ = self.planned()
        path = self.base / "rules.json"
        write_json(path, {"rules_text": "New scope restricts this project to supplied literal text only.",
                          "allowed_actions": ["analyze_text"]})
        changed = cli.governance_command(self.system,
            SimpleNamespace(cmd="project-rules", project=project, file=path))
        self.assertEqual(changed["state"], "AWAITING_GOAL")
        with self.assertRaises(ValueError):
            self.adopt(project, proposal)

    def test_external_request_32k_limit_is_checked_before_json_read(self):
        path = self.base / "external.json"
        path.write_text(json.dumps("x" * 32766), encoding="utf-8")
        self.assertEqual(path.stat().st_size, 32768)
        self.assertEqual(len(cli.request_file(path)), 32766)
        path.write_text(json.dumps("x" * 32767), encoding="utf-8")
        with patch.object(cli, "read_json", side_effect=AssertionError("Must reject before reading")):
            with self.assertRaises(ValueError):
                cli.request_file(path)

    def test_internal_record_256k_limit_still_rejects_oversize_before_read(self):
        path = self.base / "internal.json"
        path.write_text(json.dumps("x" * 262142), encoding="utf-8")
        self.assertEqual(len(cli.request_file(path, 262144)), 262142)
        path.write_text(json.dumps("x" * 262143), encoding="utf-8")
        with patch.object(cli, "read_json", side_effect=AssertionError("Must reject before reading")):
            with self.assertRaises(ValueError):
                cli.request_file(path, 262144)

    def test_credential_like_authorization_names_rejected_without_opening(self):
        # Synthetic files only; these contain no credential or key material.
        names = ["auth.json", ".env.local", "id_ed25519", "id_rsa.pub", "operator.pem", "operator.KEY", "store.pfx"]
        for name in names:
            with self.subTest(name=name):
                path = self.base / name
                path.write_text("Synthetic operator approval fixture; not a credential.", encoding="utf-8")
                with patch.object(Path, "read_text", side_effect=AssertionError("Must reject before opening")):
                    with self.assertRaises(ValueError):
                        cli.authorization_file(path)
                with patch.object(cli, "read_json", side_effect=AssertionError("Must reject before opening")):
                    with self.assertRaises(ValueError):
                        cli.request_file(path)

    def test_authorization_20k_limit_before_read_and_plain_file_works(self):
        path = self.base / "authorization.txt"
        text = "Explicit local operator approval."
        path.write_text(text, encoding="utf-8")
        self.assertEqual(cli.authorization_file(path), text)
        path.write_text("x" * 20001, encoding="utf-8")
        with patch.object(Path, "read_text", side_effect=AssertionError("Must reject before opening")):
            with self.assertRaises(ValueError):
                cli.authorization_file(path)

    def test_large_legitimate_proposal_can_be_adopted_but_is_not_approved(self):
        project, proposal, goal, result, folder = self.planned(large=True)
        self.assertGreater((folder / "proposal.json").stat().st_size, 32768)
        self.assertLess((folder / "proposal.json").stat().st_size, 262144)
        record = self.adopt(project, proposal)
        self.assertEqual(record["id"], goal)
        self.assertEqual(len(record["plan"]), 3)
        self.assertEqual(projects.get_project(self.system, project)["state"], "AWAITING_GOAL")
        self.assertEqual(self.system.db.execute("SELECT count(*) FROM tasks").fetchone()[0], 0)
        self.assertEqual(len(self.calls), 1)

    def test_adoption_requires_original_complete_claude_attempt(self):
        project, proposal, goal, result, folder = self.planned()
        self.system.db.execute("UPDATE attempts SET state='REJECTED' WHERE id=?", (result["call_id"],))
        self.system.db.commit()
        with self.assertRaises(ValueError):
            self.adopt(project, proposal)
        self.assertFalse((self.runtime / "projects" / project / "goals" / (goal + ".json")).exists())

    def test_adoption_requires_original_review_charge_not_execute_or_other_engine(self):
        project, proposal, goal, result, folder = self.planned()
        self.system.db.execute("UPDATE call_engines SET engine='codex',stage='execute' WHERE call=?", (result["call_id"],))
        self.system.db.commit()
        with self.assertRaises(ValueError):
            self.adopt(project, proposal)

    def test_proposal_cannot_be_relabelled_to_another_goal(self):
        project, proposal, goal, result, folder = self.planned()
        value = read_json(folder / "proposal.json")
        value["goal_id"] = str(uuid.uuid4())
        write_json(folder / "proposal.json", value)
        with self.assertRaises(ValueError):
            self.adopt(project, proposal)

    def test_retained_cli_value_and_proposal_plan_must_match(self):
        project, proposal, goal, result, folder = self.planned()
        value = read_json(folder / "proposal.json")
        value["plan"][0]["input"] = [999]
        write_json(folder / "proposal.json", value)
        with self.assertRaises(ValueError):
            self.adopt(project, proposal)

    def race_before_goal_lock(self, mutate):
        real_lock = self.system.lock
        changed = False

        @contextlib.contextmanager
        def acquire():
            nonlocal changed
            if not changed:
                changed = True
                mutate()
            with real_lock():
                yield
        return acquire

    def test_rules_change_between_cli_validation_and_save_rejected_under_lock(self):
        project, proposal, goal, result, folder = self.planned()
        before = (folder / "proposal.json").read_bytes()
        acquire = self.race_before_goal_lock(lambda: projects.update_rules(self.system, project,
            "Changed human rules; previous planning output must not acquire these new rules."))
        with patch.object(self.system, "lock", acquire):
            with self.assertRaises(ValueError):
                self.adopt(project, proposal)
        self.assertEqual((folder / "proposal.json").read_bytes(), before)
        self.assertFalse((self.runtime / "projects" / project / "goals" / (goal + ".json")).exists())

    def test_source_change_between_cli_validation_and_save_rejected_under_lock(self):
        project, proposal, goal, result, folder = self.planned()
        acquire = self.race_before_goal_lock(lambda: (self.source / "code.py").write_text("version = 2\n", encoding="utf-8"))
        with patch.object(self.system, "lock", acquire):
            with self.assertRaises(ValueError):
                self.adopt(project, proposal)
        self.assertFalse((self.runtime / "projects" / project / "goals" / (goal + ".json")).exists())

    def test_adopt_then_explicit_approval_and_submission_keep_fixed_task(self):
        project, proposal, goal, result, folder = self.planned()
        g = self.adopt(project, proposal)
        authorization = self.base / "authorization.txt"
        authorization.write_text("Explicit operator approval only for this exact harmless smoke plan.", encoding="utf-8")
        cli.governance_command(self.system, SimpleNamespace(cmd="goal-approve", project=project, goal=goal,
            plan_sha=g["plan_sha256"], authorization_file=authorization))
        output = cli.governance_command(self.system, SimpleNamespace(cmd="goal-submit", project=project, goal=goal, cycle=None))
        self.assertEqual(output["submitted"], [result["plan"][0]["id"]])
        row = self.system.db.execute("SELECT spec,state FROM tasks").fetchone()
        self.assertEqual(row["state"], "QUEUED")
        self.assertEqual(json.loads(row["spec"])["project_binding"]["goal_id"], goal)
        again = cli.governance_command(self.system, SimpleNamespace(cmd="goal-submit", project=project, goal=goal, cycle=None))
        self.assertEqual(again, output)
        self.assertEqual(self.system.db.execute("SELECT count(*) FROM tasks").fetchone()[0], 1)
        self.assertEqual(len(self.calls), 1)

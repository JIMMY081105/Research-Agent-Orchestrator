"""Project output, dependency and evidence isolation with explicit fake model responses."""
import copy
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / "researchops.py").is_file():
    ROOT = Path(r"E:\Github\Building-Generation-Validation")
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
import test_system as baseline
from researchops import deployment, projects, scene
from researchops.integrity import canonical, manifest, read_json, write_json


class ProjectProvenanceTests(unittest.TestCase):
    setUp = baseline.QueueTests.setUp
    tearDown = baseline.QueueTests.tearDown

    def fake(self, engine, machine, policy, prompt, schema, cwd, on_start, session):
        row = self.system.db.execute("SELECT task FROM attempts WHERE session=?", (session,)).fetchone()
        return baseline.QueueTests.fake(self, engine, machine, policy, prompt, schema,
            self.runtime / "tasks" / row["task"] / "work", on_start, session)

    def state(self, task):
        return self.system.db.execute("SELECT * FROM tasks WHERE id=?", (task,)).fetchone()

    def plan(self, dependencies=None):
        dependencies = dependencies if dependencies is not None else [[], [0]]
        project, goal = str(uuid.uuid4()), str(uuid.uuid4())
        ids = [str(uuid.uuid4()) for _ in dependencies]
        leaves = [{"id": ids[n], "action": "analyze_numbers", "input": [n + 2, 3, 7],
                   "depends_on": [ids[p] for p in parents]} for n, parents in enumerate(dependencies)]
        projects.register_project(self.system, project, "Provenance fixture", "housing",
            "Use supplied literal inputs; retained evidence must remain valid; no research writes or publication.",
            ["analyze_numbers"], kind="ops-smoke")
        g = projects.save_goal(self.system, project, goal, "Controlled low-risk dependency provenance test.",
                              leaves, purpose="ops-smoke")
        projects.approve_goal(self.system, project, goal, g["plan_sha256"],
            "Explicit local operator approval of this fixed harmless test plan and these UUIDs.")
        for leaf in leaves:
            self.system.submit(leaf["id"], leaf["action"], leaf["input"], "codex", project=project, goal=goal)
        return project, goal, [json.loads(self.state(task)["spec"]) for task in ids]

    def step(self, spec):
        with self.system.lock():
            self.system.process(self.state(spec["id"]))

    def accept(self, spec):
        self.step(spec)
        self.assertEqual(self.state(spec["id"])["state"], "AWAITING_REVIEW")
        self.step(spec)
        self.assertEqual(self.state(spec["id"])["state"], "ACCEPTED")
        return deployment.verified_acceptance(self.system, self.state(spec["id"])["spec"],
                                              {"source": manifest(self.source)})

    def change_artifact(self, spec):
        path = self.runtime / "tasks" / spec["id"] / "artifact.json"
        value = read_json(path)
        value["sum"] += 1000
        write_json(path, value)

    def test_project_output_root_and_legacy_acceptance_are_both_supported(self):
        project, goal, specs = self.plan([[]])
        spec = specs[0]
        self.assertEqual(Path(spec["workdir"]),
            self.runtime / "projects" / project / "outputs" / goal / spec["id"])
        self.accept(spec)
        legacy = str(uuid.uuid4())
        self.system.submit(legacy, "analyze_numbers", [4, 5, 6], "codex")
        legacy_spec = json.loads(self.state(legacy)["spec"])
        self.assertNotIn("project_binding", legacy_spec)
        self.assertEqual(Path(legacy_spec["workdir"]), self.runtime / "tasks" / legacy / "work")
        self.accept(legacy_spec)

    def test_parent_changed_during_child_claude_review_cannot_accept_child(self):
        project, goal, (parent, child) = self.plan()
        self.accept(parent)
        self.assertEqual(projects.dependency_status(self.system, child), "READY")
        self.step(child)
        self.on_review = lambda: self.change_artifact(parent)
        self.step(child)
        self.assertEqual(self.state(child["id"])["state"], "NEEDS_ATTENTION")
        self.assertFalse((self.runtime / "tasks" / child["id"] / "acceptance.json").exists())
        self.assertEqual(projects.dependency_status(self.system, child), "BLOCKED")
        self.assertEqual(len(self.calls), 4)

    def test_already_accepted_child_freeze_proof_and_status_reject_changed_parent(self):
        project, goal, (parent, child) = self.plan()
        self.accept(parent)
        self.accept(child)
        self.change_artifact(parent)
        with self.assertRaises((ValueError, OSError)):
            deployment.verified_acceptance(self.system, self.state(child["id"])["spec"],
                                           {"source": manifest(self.source)})
        value = projects.task_evidence_binding(self.system, child, "ACCEPTED")
        self.assertEqual(value["evidence_state"], "INVALID_EVIDENCE")
        card = projects.status_cards(self.system)[0]
        self.assertEqual(card["state"], "BLOCKED")
        accepted = deployment.accepted_tasks(self.system, {"source": manifest(self.source)}, None)
        self.assertNotIn(parent["id"], accepted)
        self.assertNotIn(child["id"], accepted)

    def test_changed_ancestor_invalidates_grandchild_without_unbounded_recursion(self):
        project, goal, (parent, child, grandchild) = self.plan([[], [0], [1]])
        for spec in (parent, child, grandchild):
            self.accept(spec)
        self.change_artifact(parent)
        self.assertEqual(projects.dependency_status(self.system, grandchild), "BLOCKED")
        with self.assertRaises((ValueError, OSError)):
            deployment.verified_acceptance(self.system, self.state(grandchild["id"])["spec"],
                                           {"source": manifest(self.source)})
        self.assertFalse(getattr(self.system, "_dependency_stack", set()))

    def test_dependency_row_cannot_borrow_other_same_goal_node_spec_and_evidence(self):
        project, goal, (never_run, donor, child) = self.plan([[], [], [0]])
        self.accept(donor)
        self.system.db.execute("UPDATE tasks SET spec=?,state='ACCEPTED' WHERE id=?",
            (self.state(donor["id"])["spec"], never_run["id"]))
        self.system.db.commit()
        self.assertEqual(projects.dependency_status(self.system, child), "BLOCKED")
        card = projects.status_cards(self.system)[0]
        self.assertEqual(card["state"], "BLOCKED")
        self.assertGreater(card["unattributed_task_record_errors"], 0)

    def test_mismatched_queue_row_cannot_reexecute_the_donor_task(self):
        project, goal, (never_run, donor) = self.plan([[], []])
        self.accept(donor)
        count = len(self.calls)
        self.system.db.execute("UPDATE tasks SET spec=? WHERE id=?",
            (self.state(donor["id"])["spec"], never_run["id"]))
        self.system.db.commit()
        self.step(never_run)
        self.assertEqual(self.state(never_run["id"])["state"], "NEEDS_ATTENTION")
        self.assertEqual(self.state(never_run["id"])["reason"], "QUEUE_TASK_ID_MISMATCH")
        self.assertEqual(self.state(donor["id"])["state"], "ACCEPTED")
        self.assertEqual(len(self.calls), count)

    def test_legacy_writer_attempt_cannot_be_borrowed_by_project_task(self):
        legacy = str(uuid.uuid4())
        self.system.submit(legacy, "analyze_numbers", [2, 3, 7], "codex")
        legacy_spec = json.loads(self.state(legacy)["spec"])
        self.accept(legacy_spec)
        project, goal, (target,) = self.plan([[]])
        self.accept(target)
        legacy_folder = self.runtime / "tasks" / legacy
        target_folder = self.runtime / "tasks" / target["id"]
        writer = read_json(legacy_folder / "writer.json")
        write_json(target_folder / "writer.json", writer)
        # Copy retained files too: rejection must not merely depend on a missing attempt directory.
        shutil.copytree(legacy_folder / "attempts" / writer["call_id"],
                        target_folder / "attempts" / writer["call_id"])
        with self.assertRaises((ValueError, OSError)):
            deployment.verified_acceptance(self.system, self.state(target["id"])["spec"],
                                           {"source": manifest(self.source)})
        self.assertEqual(projects.task_evidence_binding(self.system, target, "ACCEPTED")["evidence_state"],
                         "INVALID_EVIDENCE")

    def test_project_task_cannot_switch_to_legacy_output_root(self):
        project, goal, (target,) = self.plan([[]])
        self.accept(target)
        changed = copy.deepcopy(target)
        changed["workdir"] = str(self.runtime / "tasks" / target["id"] / "work")
        write_json(self.runtime / "tasks" / target["id"] / "spec.json", changed)
        self.system.db.execute("UPDATE tasks SET spec=? WHERE id=?", (canonical(changed).decode(), target["id"]))
        self.system.db.commit()
        self.assertFalse(projects.binding_current(self.system, changed))
        with self.assertRaises(ValueError):
            deployment.verified_acceptance(self.system, self.state(target["id"])["spec"],
                                           {"source": manifest(self.source)})

    def test_scene_worker_prompt_receives_the_same_bounded_project_context(self):
        class CapturedPrompt(Exception):
            pass
        context = {"untrusted_reference_data": True, "project_id": str(uuid.uuid4()),
                   "rules_text": "Only fit this approved room; no collision or robot capability claims."}
        fake_system = SimpleNamespace(root=self.source, runtime=self.runtime,
            project_context=Mock(return_value=context), review_feedback=Mock(return_value=None))
        spec = {"id": str(uuid.uuid4()), "input_sha256": "a" * 64, "source": {"sha256": "b" * 64},
                "writer": "codex", "workdir": str(self.base / "prompt-capture-only"),
                "input": {"skill": "fixture", "scene": "fixture", "room": "room", "profile": "fixture",
                          "clearance_m": 0.1}}
        inv = {"floor_extent_m": [4, 4], "interior_m": [3.8, 3.8], "wall_height_m": 3,
               "wall_thickness_m": 0.1, "assumptions": []}
        cand = {"candidates": [{"family": "fixture-template", "fits_room": True}]}
        tools = {"scenes": {"fixture": {"path": str(self.base / "not-read")}}}
        skills = {"fixture": {"tools": ["inventory", "candidates", "build", "check"]}}
        captured = []

        def capture(_spec, stage, engine, prompt, schema, validate):
            captured.append(prompt)
            raise CapturedPrompt()
        fake_system.call = capture
        with patch.object(scene, "registry", return_value=(tools, skills)), \
                patch.object(scene, "run_tool", side_effect=[(inv, {}), (cand, {})]), \
                patch.object(scene, "skill_context", return_value="\nFixture reference only.\n"):
            with self.assertRaises(CapturedPrompt):
                scene.execute_stage(fake_system, spec)
        data = json.loads(captured[0].split("TASK DATA\n", 1)[1])
        self.assertEqual(data["project_context"], context)
        fake_system.project_context.assert_called_once_with(spec)


if __name__ == "__main__":
    unittest.main()

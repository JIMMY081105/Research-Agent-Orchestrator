"""Project governance tests use temporary runtime/db and explicit fake model callers."""
import copy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import uuid
ROOT=Path(r"E:\Github\Building-Generation-Validation")
sys.path[:0]=[str(ROOT),str(ROOT/"tests")]
import test_system as baseline
from researchops import projects, deployment
from researchops.integrity import canonical, digest, manifest, read_json, write_json

class ProjectTests(unittest.TestCase):
    setUp=baseline.QueueTests.setUp
    tearDown=baseline.QueueTests.tearDown
    state=baseline.QueueTests.state

    def fake(self,engine,machine,policy,prompt,schema,cwd,on_start,session):
        # Explicit fake model helper uses the real ledger/session but never invokes a CLI.
        row=self.system.db.execute("SELECT task FROM attempts WHERE session=?",(session,)).fetchone()
        return baseline.QueueTests.fake(self,engine,machine,policy,prompt,schema,
                    self.runtime/"tasks"/row["task"]/"work",on_start,session)

    def project(self,kind="ops-smoke",profile="factory"):
        project=str(uuid.uuid4())
        projects.register_project(self.system,project,"Controlled fixture",profile,
            "Read supplied literals only; no research writes, GPU or publication.",
            ["analyze_numbers","analyze_text"],kind=kind)
        return project

    def goal(self,project,plan=None,purpose="ops-smoke",approve=True):
        goal=str(uuid.uuid4());plan=plan or [{"id":str(uuid.uuid4()),"action":"analyze_numbers","input":[2,3,7]}]
        record=projects.save_goal(self.system,project,goal,"Explicit bounded literal-number test goal.",plan,purpose=purpose)
        if approve:
            projects.approve_goal(self.system,project,goal,record["plan_sha256"],
                "Explicit local operator approval for this fixed bounded test plan.")
        return goal,record

    def spec(self,project,goal,leaf):
        self.system.submit(leaf["id"],leaf["action"],leaf["input"],"codex",project=project,goal=goal)
        return json.loads(self.state(leaf["id"])["spec"])

    def test_default_research_project_never_dispatches_or_creates_fake_goal(self):
        project=self.project(kind="research")
        p=projects.get_project(self.system,project)
        self.assertEqual(p["state"],"AWAITING_GOAL");self.assertIsNone(p["active_goal"])
        self.assertEqual(self.system.calls_today(),0)
        self.assertEqual(self.system.db.execute("SELECT count(*) FROM tasks").fetchone()[0],0)
        self.assertFalse((self.runtime/"projects"/project/"goals").exists())
        with self.assertRaises(ValueError):
            projects.binding_for_submission(self.system,project,str(uuid.uuid4()),"analyze_numbers","codex")

    def test_six_profiles_share_roles_without_factory_threshold_defaults(self):
        for profile in projects.PROFILES:
            project=self.project(profile=profile)
            p=projects.get_project(self.system,project)
            self.assertEqual(p["roles"],{"coordinator":"claude","reviewer":"claude","worker":"codex","final_merge":"user"})
            self.assertEqual(p["profile"],profile)
            self.assertNotIn("density",p["rules"])

    def test_registration_is_idempotent_but_id_cannot_change_identity(self):
        project=self.project()
        p=projects.get_project(self.system,project)
        same=projects.register_project(self.system,project,p["name"],p["profile"],p["rules"]["text"],
                p["rules"]["allowed_actions"],kind="ops-smoke")
        self.assertEqual(same,p)
        with self.assertRaises(ValueError):
            projects.register_project(self.system,project,"Different project","office",p["rules"]["text"],
                    p["rules"]["allowed_actions"],kind="ops-smoke")

    def test_no_unregistered_action_or_arbitrary_command(self):
        with self.assertRaises(ValueError):
            projects.register_project(self.system,str(uuid.uuid4()),"Test","factory","Rules are bounded literals.",
                                      ["powershell.exe -Command anything"])
        with self.assertRaises(ValueError):
            projects.register_project(self.system,str(uuid.uuid4()),"Test","factory","Rules are bounded literals.",
                                      ["nonexistent.action"])

    def test_canonical_ids_and_scoped_existing_read_roots(self):
        for value in ("../outside","ABC","00000000-0000-0000-0000-00000000000A"):
            with self.assertRaises(ValueError):
                projects.register_project(self.system,value,"Test","factory","Rules are bounded literals.",["analyze_numbers"])
        for root in ("relative",str(Path(self.source.anchor)),str(self.base/"missing"),str(self.base/"x"/".."/"source")):
            with self.assertRaises(ValueError):
                projects.register_project(self.system,str(uuid.uuid4()),"Test","factory","Rules are bounded literals.",
                                          ["analyze_numbers"],[root])
        project=str(uuid.uuid4())
        p=projects.register_project(self.system,project,"Test","factory","Rules are bounded literals.",
                                    ["analyze_numbers"],[str(self.source)])
        self.assertEqual(p["rules"]["readonly_roots"],[str(self.source)])

    def test_proposal_does_not_equal_approval(self):
        project=self.project();goal,g=self.goal(project,approve=False)
        self.assertIsNone(projects.get_project(self.system,project)["active_goal"])
        with self.assertRaises(ValueError):
            projects.binding_for_submission(self.system,project,goal,"analyze_numbers","codex")
        self.assertEqual(self.system.calls_today(),0)

    def test_approval_checks_exact_plan_hash_and_retains_research_future_path(self):
        project=self.project(kind="research");goal,g=self.goal(project,purpose="research",approve=False)
        with self.assertRaises(ValueError):
            projects.approve_goal(self.system,project,goal,"0"*64,"Explicit approval cannot cover a different plan.")
        a=projects.approve_goal(self.system,project,goal,g["plan_sha256"],"Explicit future user approval of this exact low-risk plan.")
        self.assertEqual(a["capabilities"],{"research_write":False,"gpu":False,"publish":False})
        self.assertEqual(projects.get_project(self.system,project)["state"],"ACTIVE")

    def test_active_plan_binds_id_action_input_roles_and_output_root(self):
        project=self.project();goal,g=self.goal(project);leaf=g["plan"][0]
        spec=self.spec(project,goal,leaf)
        self.assertTrue(projects.binding_current(self.system,spec))
        self.assertEqual(spec["workdir"],str(self.runtime/"projects"/project/"outputs"/goal/leaf["id"]))
        self.assertEqual(projects.project_context(self.system,spec)["roles"]["worker"],"codex")
        for change in ({"id":str(uuid.uuid4())},{"input":[99]},{"writer":"claude"},{"workdir":str(self.base/"outside")}):
            bad=copy.deepcopy(spec);bad.update(change)
            self.assertFalse(projects.binding_current(self.system,bad))
        with self.assertRaises(ValueError):
            self.system.submit(str(uuid.uuid4()),"analyze_numbers",[2,3,7],"codex",project=project,goal=goal)

    def test_unknown_project_binding_field_is_not_ignored(self):
        project=self.project();goal,g=self.goal(project);spec=self.spec(project,goal,g["plan"][0])
        spec["project_binding"]["command"]="anything"
        self.assertFalse(projects.binding_current(self.system,spec))

    def test_rules_change_invalidates_bindings_without_rewriting_old_goal_or_approval(self):
        project=self.project();goal,g=self.goal(project);spec=self.spec(project,goal,g["plan"][0])
        p=projects.get_project(self.system,project);directory=self.runtime/"projects"/project
        old_goal=(directory/"goals"/(goal+".json")).read_bytes()
        old_approval=(directory/"approvals"/(p["approval_sha256"]+".json")).read_bytes()
        projects.update_rules(self.system,project,"A stricter revised rule; preserve all previous results.")
        self.assertFalse(projects.binding_current(self.system,spec))
        self.assertEqual((directory/"goals"/(goal+".json")).read_bytes(),old_goal)
        self.assertEqual((directory/"approvals"/(p["approval_sha256"]+".json")).read_bytes(),old_approval)
        self.assertEqual(projects.status_cards(self.system)[0]["state"],"STALE_BINDING")

    def test_uncommitted_source_change_invalidates_goal(self):
        project=self.project();goal,g=self.goal(project);spec=self.spec(project,goal,g["plan"][0])
        (self.source/"code.py").write_text("version = 99\n",encoding="utf-8")
        self.assertFalse(projects.binding_current(self.system,spec))

    def test_content_tampering_is_rejected_not_treated_as_new_approval(self):
        project=self.project();goal,g=self.goal(project)
        path=self.runtime/"projects"/project/"goals"/(goal+".json")
        changed=read_json(path);changed["plan"][0]["input"]=[88];write_json(path,changed)
        with self.assertRaises(ValueError):
            projects.get_goal(self.system,project,goal)
        self.assertEqual(projects.status_cards(self.system)[0]["state"],"BLOCKED")

    def test_plan_limits_unknown_fields_foreign_dependencies_and_cycles_fail(self):
        project=self.project()
        a,b=str(uuid.uuid4()),str(uuid.uuid4())
        bad_plans=[
            [{"id":a,"action":"analyze_numbers","input":[2],"shell":"bad"}],
            [{"id":a,"action":"analyze_numbers","input":[2],"depends_on":[b]}],
            [{"id":a,"action":"analyze_numbers","input":[2],"depends_on":[a]}],
            [{"id":a,"action":"analyze_numbers","input":[2],"depends_on":[b]},
             {"id":b,"action":"analyze_numbers","input":[3],"depends_on":[a]}],
            [{"id":str(uuid.uuid4()),"action":"analyze_numbers","input":[2]} for _ in range(13)]]
        for plan in bad_plans:
            with self.assertRaises(ValueError):
                projects.save_goal(self.system,project,str(uuid.uuid4()),"A bounded proposed goal text.",plan,purpose="ops-smoke")

    def test_smoke_kind_cannot_approve_scientific_scene_action(self):
        with self.assertRaises(ValueError):
            projects.register_project(self.system,str(uuid.uuid4()),"Smoke","factory","Controlled test rules.",
                                      ["scene_stair_workflow"],kind="ops-smoke")

    def test_approval_never_expands_gpu_research_write_or_publish(self):
        project=self.project();goal,g=self.goal(project,approve=False)
        for capability in ("gpu","research_write","publish"):
            self.system.policy[capability]=True
            with self.assertRaises(ValueError):
                projects.approve_goal(self.system,project,goal,g["plan_sha256"],"Explicit low-risk plan approval only.")
            self.system.policy[capability]=False

    def test_legacy_task_without_project_binding_is_unchanged(self):
        self.assertTrue(projects.binding_current(self.system,{"id":"legacy"}))
        self.assertEqual(projects.project_context(self.system,{"id":"legacy"}),{})
        self.assertEqual(projects.dependency_status(self.system,{"id":"legacy"}),"READY")

    def test_dependency_waits_then_reverifies_real_retained_parent_evidence(self):
        project=self.project();a,b=str(uuid.uuid4()),str(uuid.uuid4())
        plan=[{"id":a,"action":"analyze_numbers","input":[2,3,7]},
              {"id":b,"action":"analyze_numbers","input":[1],"depends_on":[a]}]
        goal,g=self.goal(project,plan)
        parent=self.spec(project,goal,g["plan"][0]);child=self.spec(project,goal,g["plan"][1])
        self.assertEqual(projects.dependency_status(self.system,child),"WAITING")
        self.system.tick();self.system.tick()
        self.assertEqual(self.state(a)["state"],"ACCEPTED")
        # Parent uses genuine production schema/ledger/attempt/process/result/acceptance files;
        # only the model's in-memory response was an explicitly declared fake.
        deployment.verified_acceptance(self.system,canonical(parent).decode(),{"source":manifest(self.source)})
        self.assertEqual(projects.dependency_status(self.system,child),"READY")
        p=self.runtime/"tasks"/a/"artifact.json";value=read_json(p);value["sum"]=999;write_json(p,value)
        self.assertEqual(projects.dependency_status(self.system,child),"BLOCKED")

    def test_accepted_state_without_actual_evidence_never_satisfies_dependency(self):
        project=self.project();a,b=str(uuid.uuid4()),str(uuid.uuid4())
        goal,g=self.goal(project,[{"id":a,"action":"analyze_numbers","input":[2]},
                                 {"id":b,"action":"analyze_numbers","input":[1],"depends_on":[a]}])
        self.spec(project,goal,g["plan"][0]);child=self.spec(project,goal,g["plan"][1])
        self.system.db.execute("UPDATE tasks SET state='ACCEPTED' WHERE id=?",(a,));self.system.db.commit()
        self.assertEqual(projects.dependency_status(self.system,child),"BLOCKED")

    def test_failed_parent_blocks_downstream(self):
        project=self.project();a,b=str(uuid.uuid4()),str(uuid.uuid4())
        goal,g=self.goal(project,[{"id":a,"action":"analyze_numbers","input":[2]},
                                 {"id":b,"action":"analyze_numbers","input":[1],"depends_on":[a]}])
        self.spec(project,goal,g["plan"][0]);child=self.spec(project,goal,g["plan"][1])
        self.system.state(a,"NEEDS_ATTENTION","EXPLICIT_TEST_FAILURE")
        self.assertEqual(projects.dependency_status(self.system,child),"BLOCKED")

    def test_mutations_share_controller_lock_while_binding_readers_are_pure(self):
        project=self.project();goal,g=self.goal(project)
        from researchops.core import Busy
        with self.system.lock():
            with self.assertRaises(Busy):
                projects.update_rules(self.system,project,"Another bounded rule change.")
            binding=projects.binding_for_submission(self.system,project,goal,"analyze_numbers","codex")
        self.assertEqual(binding["project_id"],project)
        self.assertEqual(self.system.calls_today(),0)

    def test_reparse_symlink_record_rejected_before_write_or_read(self):
        target=self.base/"outside";target.mkdir()
        root=self.runtime/"projects";root.mkdir()
        project=str(uuid.uuid4());link=root/project
        try:
            os.symlink(target,link,target_is_directory=True)
        except OSError:
            try:
                import _winapi
                _winapi.CreateJunction(str(target),str(link))
            except (OSError,ImportError,AttributeError):
                self.skipTest("Host permits neither isolated symlink nor junction fixture")
        with self.assertRaises(ValueError):
            projects.register_project(self.system,project,"Test","factory","Rules are bounded literals.",["analyze_numbers"])
        self.assertEqual(list(target.iterdir()),[])

    def test_status_card_uses_actual_content_hashes_and_reports_blocked_artifact(self):
        project=self.project();goal,g=self.goal(project);leaf=g["plan"][0]
        self.spec(project,goal,leaf);self.system.run_ready()
        card=projects.status_cards(self.system)[0]
        self.assertEqual(card["state"],"ACCEPTED")
        binding=card["tasks"][0]["content_binding"]
        self.assertEqual(binding["evidence_state"],"VERIFIED_ACCEPTANCE")
        self.assertEqual(binding["input_sha256"],leaf["input_sha256"])
        self.assertEqual(binding["artifact_sha256"],digest(canonical(read_json(self.runtime/"tasks"/leaf["id"]/"artifact.json"))))
        path=self.runtime/"tasks"/leaf["id"]/"artifact.json";value=read_json(path);value["sum"]=800;write_json(path,value)
        card=projects.status_cards(self.system)[0]
        self.assertEqual(card["state"],"BLOCKED")
        self.assertEqual(card["tasks"][0]["content_binding"]["evidence_state"],"INVALID_EVIDENCE")

    def test_status_cannot_call_partially_submitted_plan_accepted(self):
        project=self.project()
        goal,g=self.goal(project,[{"id":str(uuid.uuid4()),"action":"analyze_numbers","input":[2]},
                                 {"id":str(uuid.uuid4()),"action":"analyze_numbers","input":[3]}])
        self.spec(project,goal,g["plan"][0]);self.system.run_ready()
        self.assertNotEqual(projects.status_cards(self.system)[0]["state"],"ACCEPTED")

    def test_corrupt_queue_row_is_visible_blocker_not_silently_hidden(self):
        self.project()
        self.system.db.execute("INSERT INTO tasks(id,spec,state,created,updated) VALUES(?,?,?,?,?)",
                (str(uuid.uuid4()),"{broken","NEEDS_ATTENTION","2040-01-01","2040-01-01"))
        self.system.db.commit()
        card=projects.status_cards(self.system)[0]
        self.assertEqual(card["state"],"BLOCKED")
        self.assertEqual(card["unattributed_task_record_errors"],1)
        self.assertEqual(card["blocking_reason"],"INVALID_QUEUE_RECORD_REQUIRES_INSPECTION")

if __name__=="__main__":unittest.main(verbosity=2)

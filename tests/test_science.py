"""Offline failure controls; these fixtures never pretend to be real USD runs."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

from researchops import evidence
from researchops.integrity import canonical,digest,write_json

from researchops import science
MODULE_PATH=Path(science.__file__)



def observation(ok=True):
    checks={key:True for key in science.CHECKS}
    checks["every_mesh_has_collider"]=ok
    return {"checks":checks,"measured":{"mesh_count":64,"tread_count":19},"not_verified":["native physics"]}


def case(result):
    return {"result":result,"run":{"ok":True,"exit_code":0,"process":{"pid":99999999,"birth":"123456"}}}


class Fixture:
    def __init__(self,root):
        self.root=root
        self.task_id=str(uuid.uuid4());self.task=root/"tasks"/self.task_id
        self.task.mkdir(parents=True)
        self.source={"researchops/scene_runner.py":digest(b"# fixture checker source\n")}
        self.spec={"id":self.task_id,"input":{"profile":"school"},"workdir":str(self.task/"work"),
                   "source":{"files":self.source,"sha256":digest(canonical(self.source))}}
        self.spec["input_sha256"]=digest(canonical(self.spec["input"]))
        self.params={"profile":"school","rise_m":3.2,"room_interior_m":[6.9,4.9],"clearance_m":0.1,
            "family":"u_shaped","expected_tread_count":19,"expected_footprint_m":[2.85,4.54]}
        asset=self.task/"work/exec-test/stair.build_usd";asset.mkdir(parents=True)
        (asset/"stair.usda").write_bytes(b"# fixture only: PhysicsCollisionAPI\n")
        (asset/"traversal_path.json").write_text('{"points_m":[[0,0,0],[0,0,3.2]]}',encoding="utf-8")
        self.artifact={"task_id":self.task_id,"input_sha256":self.spec["input_sha256"],
            "source_sha256":self.spec["source"]["sha256"],"checks":{"every_mesh_has_collider":True},
            "tool_runs":[{"tool":"stair.build_usd","ok":True,"exit_code":0,"outputs":{
                p.relative_to(self.task/"work").as_posix():digest(p.read_bytes()) for p in asset.iterdir()}},
                {"tool":"stair.check_usd","ok":True,"exit_code":0,"params":self.params}]}
        binding=digest(canonical({"spec":self.spec,"artifact":self.artifact}))
        acceptance={"source_sha256":self.spec["source"]["sha256"],"artifact_sha256":digest(canonical(self.artifact)),
                    "binding_sha256":binding,"review_call":str(uuid.uuid4())}
        review={"review":{"task_id":self.task_id,"binding_sha256":binding,"verdict":"PASS","issues":[]},
                "call_id":acceptance["review_call"]}
        for name,value in (("spec",self.spec),("artifact",self.artifact),("acceptance",acceptance),("review",review)):
            write_json(self.task/(name+".json"),value)
        self.historical=science.baseline(self.task)

    def bundle(self):
        work=self.root/"science-runs"/str(uuid.uuid4());work.mkdir(parents=True)
        copied_source=work/"source/project/researchops/scene_runner.py";copied_source.parent.mkdir(parents=True)
        copied_source.write_bytes(b"# fixture checker source\n")
        checker=work/"source/checker.py";checker.write_bytes(MODULE_PATH.read_bytes())
        evaluator=work/"source/evaluator.py";evaluator.write_bytes(Path(evidence.__file__).read_bytes())
        report={"workdir":str(work),"level":science.LEVEL,"status":"PASS","passed":True,
            "source_sha256":self.spec["source"]["sha256"],"baseline":self.historical,
            "source_files":[{"path":p.relative_to(work).as_posix(),"sha256":digest(p.read_bytes())}
                            for p in (copied_source,checker,evaluator)],"cases":{}}
        for role in ("target","positive","negative"):
            asset=work/"assets"/role;asset.mkdir(parents=True)
            for name,entry in self.historical["files"].items():
                (asset/name).write_bytes(Path(entry["path"]).read_bytes())
            if role=="negative":(asset/"stair.usda").write_bytes(b"# fixture only: no CollisionAPI\n")
            stage=work/("check-"+role);base=stage/"_sandbox/base";base.mkdir(parents=True)
            (base/"scene_runner.py").write_bytes(copied_source.read_bytes())
            inputs=stage/"_sandbox/inputs-stair.check_usd";inputs.mkdir(parents=True)
            for name in ("stair.usda","traversal_path.json"):(inputs/name).write_bytes((asset/name).read_bytes())
            out=stage/"stair.check_usd";out.mkdir()
            identity={"pid":99999999,"birth":"123456"}
            write_json(out/"process.json",{**identity,"tool":"stair.check_usd"})
            write_json(out/"request.json",{"tool":"stair_check","params":self.params,
                "inputs":{"stair_usda":str(inputs/"stair.usda")},"out_dir":str(out),"buildingsgen_src":str(base/"src")})
            result=observation(role!="negative");write_json(out/"result.json",{"ok":True,"result":result})
            lease=str(uuid.uuid4())+".json"
            write_json(work/"control-runtime/tool-leases"/lease,{"state":"CLOSED","child":identity,
                "name":"BGV.Tool."+uuid.uuid4().hex,"network_capabilities":[],"capabilities":["registryRead"]})
            run={"tool":"stair.check_usd","runner":"stair_check","params":self.params,"ok":True,"exit_code":0,
                 "process":identity,"outputs":{p.relative_to(work).as_posix():digest(p.read_bytes()) for p in out.iterdir()},
                 "sandbox":{"base":base.relative_to(work).as_posix(),"base_sha256":science.appcontainer.hash_tree(base),
                    "inputs":inputs.relative_to(work).as_posix(),"input_sha256":science.appcontainer.hash_tree(inputs),"lease":lease}}
            receipt=work/"control-receipts"/(role+".json");write_json(receipt,run)
            report["cases"][role]={"result":result,"run":run,"receipt_sha256":digest(receipt.read_bytes())}
        mutlease=work/"control-runtime/tool-leases"/(str(uuid.uuid4())+".json")
        write_json(mutlease,{"state":"CLOSED","child":{"pid":99999999,"birth":"123456"},
                            "network_capabilities":[],"capabilities":["registryRead"]})
        report["mutation"]={"exit_code":0,"program_sha256":digest(science.REMOVE_COLLISION_PROGRAM.encode()),
            "lease":str(mutlease),"process":{"pid":99999999,"birth":"123456"},"outputs":{},
            "result":{"removed":64,"geometry_sha256_before":"f"*64,"geometry_sha256_after":"f"*64}}
        write_json(work/"report.json",report)
        return work,report


class ScienceTests(unittest.TestCase):
    def setUp(self):
        base=Path(__file__).resolve().parents[1]/".runtime/tests/science";base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base)
        self.root=Path(self.temp.name)
        self.fixture=Fixture(self.root)
    def tearDown(self):self.temp.cleanup()
    def bundle(self):return self.fixture.bundle()
    def assessment(self,work):
        store=evidence.EvidenceStore(self.root)
        with patch.object(science.winproc,"identity",return_value=None):
            return science.reconstruct_assessment(store,store.fingerprint((work/"report.json").relative_to(self.root).as_posix()))
    def test_content_failure_is_required_even_when_exit_zero(self):
        cases={"target":case(observation()),"positive":case(observation()),"negative":case(observation(False))}
        self.assertTrue(science.controls_pass(cases))
        cases["negative"]["result"]=observation()
        self.assertFalse(science.controls_pass(cases))
    def test_crash_network_missing_result_not_a_negative_control(self):
        for changed in ({"ok":False},{"exit_code":2},{"exit_code":True},{"process":{"pid":1,"birth":"UNKNOWN"}}):
            cases={"target":case(observation()),"positive":case(observation()),"negative":case(observation(False))}
            cases["negative"]["run"].update(changed)
            self.assertFalse(science.controls_pass(cases))
    def test_wrong_scientific_reason_and_nonboolean_checks_rejected(self):
        cases={"target":case(observation()),"positive":case(observation()),"negative":case(observation(False))}
        cases["negative"]["result"]["checks"]["reopened_by_usd"]=False
        self.assertFalse(science.controls_pass(cases))
        cases["negative"]["result"]=observation(False);cases["positive"]["result"]["checks"]["z_up_metres"]=1
        self.assertFalse(science.controls_pass(cases))
    def test_target_positive_exact_and_negative_geometry_unchanged(self):
        cases={"target":case(observation()),"positive":case(observation()),"negative":case(observation(False))}
        cases["negative"]["result"]["measured"]["mesh_count"]=63
        self.assertFalse(science.controls_pass(cases))
    def test_old_acceptance_and_source_manifest_must_bind(self):
        self.assertEqual(science.baseline(self.fixture.task),self.fixture.historical)
        spec=copy.deepcopy(self.fixture.spec);spec["source"]["files"]["extra.py"]="0"*64
        write_json(self.fixture.task/"spec.json",spec)
        with self.assertRaises(ValueError):science.baseline(self.fixture.task)
    def test_changed_historical_asset_rejected_without_touching_old_record(self):
        original=(self.fixture.task/"acceptance.json").read_bytes()
        p=Path(self.fixture.historical["files"]["stair.usda"]["path"]);p.write_bytes(b"changed fixture")
        with self.assertRaises(ValueError):science.baseline(self.fixture.task)
        self.assertEqual((self.fixture.task/"acceptance.json").read_bytes(),original)
    def test_absolute_owned_roots_required(self):
        with self.assertRaises(ValueError):science._absolute("relative")
        with self.assertRaises(ValueError):science._owned(self.root,self.root)
        with self.assertRaises(ValueError):science._owned(self.root.parent/"outside",self.root)
    def test_fresh_issued_static_only_assessment_not_full_ready(self):
        work,_=self.bundle();result=self.assessment(work)
        self.assertTrue(evidence.issued_assessment(result));self.assertEqual(result["status"],"READY")
        self.assertEqual(result["layer"],"STATIC_GEOMETRY")
        sample=evidence.summarize_sample(self.fixture.task_id,[result])
        self.assertEqual(sample["status"],"UNVERIFIED");self.assertEqual(len(sample["missing_layers"]),3)
    def test_dict_cannot_mint_an_assessment(self):
        store=evidence.EvidenceStore(self.root)
        with self.assertRaises(evidence.EvidenceError):science.reconstruct_assessment(store,{"process_verified":True})
    def test_missing_or_live_owner_receipt_blocks_even_if_json_claims_verified(self):
        work,report=self.bundle();role="negative";run=report["cases"][role]["run"]
        lease=work/"control-runtime/tool-leases"/run["sandbox"]["lease"]
        value=json.loads(lease.read_text());value["state"]="RUNNING";value["process_verified"]=True
        write_json(lease,value)
        with self.assertRaises(evidence.EvidenceError):self.assessment(work)
    def test_changed_result_and_extra_output_rejected_before_evaluation(self):
        work,_=self.bundle();(work/"check-negative/stair.check_usd/result.json").write_text('{}')
        with self.assertRaises(evidence.EvidenceError):self.assessment(work)
        work,_=self.bundle();(work/"check-negative/stair.check_usd/extra.txt").write_text('fixture')
        with self.assertRaises(evidence.EvidenceError):self.assessment(work)
    def test_stale_copied_runtime_or_input_rejected(self):
        for relative in ("check-target/_sandbox/base/scene_runner.py","assets/negative/stair.usda"):
            work,_=self.bundle();(work/relative).write_text('changed fixture')
            with self.assertRaises(evidence.EvidenceError):self.assessment(work)
    def test_checker_source_must_be_exact_current_copy_not_arbitrary_python(self):
        work,report=self.bundle();p=work/"source/checker.py";p.write_text("raise RuntimeError('DO_NOT_EXECUTE')\n")
        for row in report["source_files"]:
            if row["path"]=="source/checker.py":row["sha256"]=digest(p.read_bytes())
        write_json(work/"report.json",report)
        with self.assertRaises(evidence.EvidenceError):self.assessment(work)
    def test_consistently_rehashed_different_control_dependencies_still_rejected(self):
        work,report=self.bundle()
        base=work/"check-positive/_sandbox/base"
        (base/"different_dependency.py").write_text("value=2\n",encoding="utf-8")
        run=report["cases"]["positive"]["run"]
        run["sandbox"]["base_sha256"]=science.appcontainer.hash_tree(base)
        receipt=work/"control-receipts/positive.json";write_json(receipt,run)
        report["cases"]["positive"]["receipt_sha256"]=digest(receipt.read_bytes())
        write_json(work/"report.json",report)
        with self.assertRaisesRegex(evidence.EvidenceError,"CONTROL_RUNTIME_CLOSURE_DIFFERS"):
            self.assessment(work)
    def test_negative_mutation_network_capability_is_not_trusted(self):
        work,report=self.bundle()
        lease=Path(report["mutation"]["lease"])
        value=json.loads(lease.read_text());value["network_capabilities"]=["internetClient"]
        write_json(lease,value)
        with self.assertRaisesRegex(evidence.EvidenceError,"NEGATIVE_MUTATION_OWNER_INVALID"):
            self.assessment(work)
    def test_native_layers_are_never_claimed(self):
        self.assertEqual(science.LEVEL,"STATIC_GEOMETRY")
        self.assertIn("UNVERIFIED"," ".join(science.LIMITS))
        self.assertNotIn("subprocess",science.REMOVE_COLLISION_PROGRAM)
        self.assertNotIn("Save(",science.REMOVE_COLLISION_PROGRAM)


if __name__=="__main__":
    started=__import__('time').monotonic();stream=io.StringIO()
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ScienceTests))
    receipt={"tests":result.testsRun,"passed":result.wasSuccessful(),"seconds":round(__import__('time').monotonic()-started,3),
             "source_sha256":digest(MODULE_PATH.read_bytes()),"output":stream.getvalue()}
    write_json(Path(__file__).resolve().parents[1]/".runtime/science-unit-receipt.json",receipt)
    print(stream.getvalue());raise SystemExit(0 if result.wasSuccessful() else 1)

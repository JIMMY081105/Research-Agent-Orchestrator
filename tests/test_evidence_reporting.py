"""Synthetic unit fixtures only: no Isaac, navigation, robot, model or live queue execution."""
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from researchops.evidence import (Binding, EvidenceError, EvidenceStore, FileRef, GateContract, RegisteredChecker,
                                 TrustedRun, evaluate_gate, summarize_batch, summarize_sample, SCIENCE_LAYERS)
from researchops.reporting import ImagePair, RenderImage, create_daily_report, inspect_pair, png_info

CHECKER = '''from researchops.evidence import Observation
def check(store, run):
 data=store.json(run.binding.artifacts[0])
 if data.get("tool_error"):return Observation("BLOCKED","TOOL_ERROR")
 if data.get("collision_count",0)>0:return Observation("PASS","COLLISION_PRESENT")
 return Observation("FAIL",data.get("failure_reason","COLLISION_MISSING"))
'''


def png(variant=0, uniform=False):
    def chunk(kind, data):
        return struct.pack(">I", len(data))+kind+data+struct.pack(">I", zlib.crc32(kind+data)&0xffffffff)
    rows = bytearray()
    for y in range(24):
        rows.append(0)
        for x in range(24):
            rows.extend((128, 64, 32) if uniform else ((x*9+variant)%256, (y*9)%256, (x+y+variant)%256))
    return b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR", struct.pack(">IIBBBBB",24,24,8,2,0,0,0))+chunk(b"IDAT",zlib.compress(rows))+chunk(b"IEND",b"")


class CandidateTests(unittest.TestCase):
    def setUp(self):
        temporary = ROOT/".runtime/tests/evidence"
        temporary.mkdir(parents=True,exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temporary)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = EvidenceStore(self.root)
        self.write("source/checker.py", CHECKER.encode())
        self.write("source/config.json", b'{"threshold":1}')
        spec = importlib.util.spec_from_file_location("fixed_checker_fixture", self.root/"source/checker.py")
        self.module = importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)
        self.sources = (self.ref("source/checker.py"), self.ref("source/config.json"))
        self.checkers = {"static.check": RegisteredChecker("static.check", self.module.check, self.sources[0], scientific_reasons=("COLLISION_PRESENT","COLLISION_MISSING","OTHER_FAILURE"))}
        self.runs = {}
        for role, count in (("target",2),("positive",2),("negative",0)):
            self.new_run(role, count)
        self.contract = GateContract("g-static", "sample-001", "STATIC_GEOMETRY", "static.check",
                                     self.runs["target"], self.runs["positive"], self.runs["negative"],
                                     "COLLISION_MISSING", ("door-a",), seeds=(7,))
        self.write("verification/status.json", b'{"review_limit":50,"reviews_today":33,"engine_calls_today":{"codex":50,"claude":25}}')
        self.budget = self.ref("verification/status.json")

    def write(self, name, data):
        path = self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)

    def ref(self, name):
        return self.store.fingerprint(name)

    def new_run(self, role, count, **extra):
        self.write(f"verification/{role}/input.json", json.dumps({"case":"door-a","seed":7,"role":role}).encode())
        self.write(f"verification/{role}/artifact.json", json.dumps({"collision_count":count,"claimed_status":"PASS",**extra}).encode())
        self.write(f"verification/{role}/receipt.json", b'{"unit_fixture":true,"not_a_live_run":true}')
        binding = Binding(self.sources,(self.ref(f"verification/{role}/input.json"),),(self.ref(f"verification/{role}/artifact.json"),))
        run = TrustedRun(role,"static.check",self.ref(f"verification/{role}/receipt.json"),binding,("door-a",),(7,),role,True,0,True)
        self.runs[role] = run
        return run

    def gate(self, **changes):
        return evaluate_gate(self.store, replace(self.contract, **changes), self.runs, self.checkers)

    def sample(self):
        return summarize_sample("sample-001",[self.gate()])

    def report(self, **changes):
        options=dict(project="BGV",date="2026-10-19",tasks=[{"task_id":"task-001","owner":"User","stage":"STATIC_GEOMETRY","assessment":self.sample()}],budget_ref=self.budget)
        options.update(changes)
        return create_daily_report(self.store,"daily/report",**options)

    def render_pair(self, rights="UNKNOWN"):
        images=[]
        for mode, variant in (("BEAUTY",0),("COLLISION",5)):
            name="verification/images/"+mode.lower()+".png";self.write(name,png(variant))
            image=self.ref(name)
            data={"kind":"RENDER_CAPTURE","view_id":"overview","mode":mode,"asset_sha256":"a"*64,"camera_sha256":"b"*64,"image_sha256":image.sha256,"completed":True,"unit_fixture":True,"not_live_render":True}
            receipt="verification/images/"+mode.lower()+".json";self.write(receipt,json.dumps(data).encode())
            run=TrustedRun(mode,"render.fixture",self.ref(receipt),Binding(self.sources,(self.runs["target"].binding.inputs[0],),(image,)),("overview",),(7,),"target",True,0,True)
            self.runs[mode]=run
            permission="verification/images/"+mode.lower()+"-permission.json"
            self.write(permission,json.dumps({"image_sha256":image.sha256,"permission":"COPY_FOR_LOCAL_REPORT","authority":"unit fixture generator"}).encode())
            images.append(RenderImage(image,run.receipt,mode,"overview",mode,"a"*64,"b"*64,rights,self.ref(permission)))
        return ImagePair("overview",*images)

    def test_valid_controls_allow_only_single_static_layer(self):
        self.assertEqual(self.gate()["status"],"READY")
        self.assertEqual(self.sample()["status"],"UNVERIFIED")
        self.assertIn("ROBOT_BEHAVIOR",self.sample()["missing_layers"])

    def test_self_consistent_claimed_pass_is_recomputed_from_artifact(self):
        target=self.new_run("target",0)
        result=self.gate(target=target)
        self.assertEqual((result["status"],result["reason"]),("FAIL","COLLISION_MISSING"))

    def test_self_written_receipts_not_in_registry_cannot_mint_pass(self):
        result=evaluate_gate(self.store,self.contract,{},self.checkers)
        self.assertEqual((result["status"],result["reason"]),("BLOCKED","UNTRUSTED_RUN"))

    def test_negative_that_passes_blocks_measurement(self):
        negative=self.new_run("negative",2)
        self.assertEqual(self.gate(negative=negative)["reason"],"NEGATIVE_CONTROL_NOT_REJECTED")

    def test_wrong_negative_reason_is_rejected(self):
        negative=self.new_run("negative",0,failure_reason="OTHER_FAILURE")
        self.assertEqual(self.gate(negative=negative)["reason"],"NEGATIVE_CONTROL_REASON_MISMATCH")

    def test_tool_error_is_not_scientific_negative_success(self):
        negative=self.new_run("negative",0,tool_error=True)
        self.assertEqual(self.gate(negative=negative)["reason"],"MEASUREMENT_INFRASTRUCTURE_FAILURE")

    def test_positive_control_failure_blocks(self):
        positive=self.new_run("positive",0)
        self.assertEqual(self.gate(positive=positive)["reason"],"POSITIVE_CONTROL_FAILED")

    def test_empty_seed_set_cannot_pass_or_scientifically_fail(self):
        result=self.gate(seeds=())
        self.assertEqual((result["status"],result["reason"]),("UNVERIFIED","EMPTY_OR_INVALID_SEED_SET"))

    def test_seed_mismatch_blocks(self):
        self.assertEqual(self.gate(seeds=(8,))["reason"],"RUN_CASE_OR_SEED_MISMATCH")

    def test_missing_native_checker_remains_unverified(self):
        result=self.gate(layer="NATIVE_RUNTIME_COLLISION",checker_id="native.isaac")
        self.assertEqual(result["status"],"UNVERIFIED")

    def test_static_checker_cannot_be_relabelled_as_native_runtime(self):
        result=self.gate(layer="NATIVE_RUNTIME_COLLISION")
        self.assertEqual((result["status"],result["reason"]),("UNVERIFIED","CHECKER_NOT_REGISTERED_FOR_LAYER"))

    def test_stale_artifact_hash_is_rejected(self):
        self.write("verification/target/artifact.json",b'{"collision_count":9}')
        self.assertEqual(self.gate()["reason"],"STALE_FILE_HASH")

    def test_stale_actual_checker_source_is_rejected(self):
        self.write("source/checker.py",CHECKER.encode()+b"\n# changed\n")
        self.assertEqual(self.gate()["reason"],"STALE_FILE_HASH")

    def test_checker_code_origin_must_match_bound_real_file(self):
        self.write("source/other.py",CHECKER.encode())
        ref=self.ref("source/other.py")
        contract=self.contract
        updated={k:replace(v,binding=replace(v.binding,source=v.binding.source+(ref,))) for k,v in self.runs.items()}
        contract=replace(contract,target=updated['target'],positive=updated['positive'],negative=updated['negative'])
        result=evaluate_gate(self.store,contract,updated,{"static.check":RegisteredChecker("static.check",self.module.check,ref,scientific_reasons=("COLLISION_PRESENT","COLLISION_MISSING","OTHER_FAILURE"))})
        self.assertEqual(result["reason"],"CHECKER_SOURCE_ORIGIN_MISMATCH")

    def test_missing_artifact_blocks_instead_of_scientific_fail(self):
        (self.root/"verification/negative/artifact.json").unlink()
        self.assertEqual(self.gate()["reason"],"MISSING_FILE")

    def test_nonzero_tool_exit_is_not_scientific_fail(self):
        target=replace(self.runs["target"],exit_code=1);self.runs["target"]=target
        self.assertEqual(self.gate(target=target)["reason"],"RUN_NOT_SUCCESSFULLY_MEASURED")

    def test_duplicate_layer_rejected(self):
        self.assertEqual(summarize_sample("sample-001",[self.gate(),self.gate()])["reason"],"DUPLICATE_LAYER_EVIDENCE")

    def test_single_sample_does_not_cover_batch(self):
        result=summarize_batch(["sample-001","sample-002"],[self.sample()],2)
        self.assertEqual((result["status"],result["missing_ids"]),("UNVERIFIED",["sample-002"]))

    def test_duplicate_batch_id_rejected(self):
        result=summarize_batch(["sample-001"],[self.sample(),self.sample()],1)
        self.assertEqual(result["reason"],"BATCH_DUPLICATE_SAMPLE_ID")

    def test_batch_denominator_cannot_be_lowered(self):
        self.assertEqual(summarize_batch(["a","b"],[self.sample()],1)["reason"],"BATCH_DENOMINATOR_MISMATCH")

    def test_static_only_batch_never_ready(self):
        result=summarize_batch(["sample-001"],[self.sample()],1)
        self.assertEqual(result["status"],"UNVERIFIED")

    def test_four_self_written_ready_json_rows_cannot_mint_full_ready(self):
        forged=[{"sample_id":"sample-001","layer":layer,"status":"READY","reason":"CLAIMED_PASS","evidence":[]} for layer in SCIENCE_LAYERS]
        self.assertEqual(summarize_sample("sample-001",forged)["reason"],"UNISSUED_LAYER_ASSESSMENT")

    def test_persisted_json_requires_actual_reevaluation(self):
        reloaded=json.loads(json.dumps(self.sample()))
        self.assertEqual(summarize_batch(["sample-001"],[reloaded],1)["reason"],"UNISSUED_SAMPLE_ASSESSMENT")

    def test_report_missing_images_and_publish_false(self):
        self.write("unrelated/raw-model-output.txt",b"not included")
        report=self.report()
        self.assertEqual(report["index"]["images"][0]["status"],"MISSING")
        self.assertFalse(report["publish"])
        self.assertEqual(set(report["manifest"]["files"]),{"REPORT.md","index.json","status.svg"})
        self.assertEqual(report["index"]["models"]["review_remaining"],17)

    def test_incomplete_real_pair_is_missing(self):
        pair=self.render_pair()
        result=inspect_pair(self.store,replace(pair,collision=None),self.runs)
        self.assertEqual(result["status"],"MISSING")

    def test_unknown_copyright_images_reference_only_even_copy_requested(self):
        pair=self.render_pair()
        report=self.report(image_pairs=[pair],trusted_runs=self.runs,copy_images=True)
        self.assertEqual(report["index"]["images"][0]["status"],"PAIRED_RUNTIME_CAPTURE")
        self.assertEqual(report["index"]["images"][0]["copied"],[])
        self.assertFalse((self.root/"daily/report/images").exists())

    def test_explicitly_permitted_fixture_images_can_copy(self):
        pair=self.render_pair("USER_OWNED")
        report=self.report(image_pairs=[pair],trusted_runs=self.runs,copy_images=True)
        self.assertEqual(len(report["index"]["images"][0]["copied"]),2)
        self.assertEqual(len(report["manifest"]["files"]),5)

    def test_different_camera_pair_is_unverified(self):
        pair=self.render_pair()
        result=inspect_pair(self.store,replace(pair,collision=replace(pair.collision,camera_sha256="c"*64)),self.runs)
        self.assertEqual(result["status"],"UNVERIFIED")

    def test_untrusted_image_capture_stays_unverified(self):
        self.assertEqual(inspect_pair(self.store,self.render_pair(),{})["reason"],"UNTRUSTED_IMAGE_CAPTURE")

    def test_uniform_and_truncated_images_are_rejected(self):
        self.write("verification/blank.png",png(uniform=True))
        with self.assertRaisesRegex(EvidenceError,"BLANK_OR_TRIVIAL_IMAGE"):
            png_info(self.store,self.ref("verification/blank.png"))
        self.write("verification/broken.png",png()[:-8])
        with self.assertRaises(EvidenceError):png_info(self.store,self.ref("verification/broken.png"))

    def test_unsafe_paths_and_credentials_refused_before_read(self):
        cases={"../outside.json":"UNSAFE_PATH","E:/secret.json":"UNSAFE_PATH","dir\\file.json":"UNSAFE_PATH",
               "x/.env":"SENSITIVE_PATH_REFUSED","machine.json":"SENSITIVE_PATH_REFUSED","x/id_ed25519":"SENSITIVE_PATH_REFUSED","x/file.pem":"SENSITIVE_PATH_REFUSED"}
        for path, reason in cases.items():
            with self.subTest(path=path),self.assertRaises(EvidenceError) as error:self.store.fingerprint(path)
            self.assertEqual(error.exception.reason,reason)

    def test_absolute_and_escape_report_output_refused(self):
        options=dict(project="BGV",date="2026-10-19",tasks=[],budget_ref=self.budget)
        for path in ("../export","C:/export"):
            with self.assertRaises(EvidenceError):create_daily_report(self.store,path,**options)

    def test_publish_true_is_rejected(self):
        with self.assertRaisesRegex(EvidenceError,"PUBLISH_NOT_AUTHORIZED"):self.report(publish=True)

    def test_raw_hidden_reasoning_field_cannot_enter_bundle(self):
        assessment=self.sample();assessment["hidden_reasoning"]="never serialize"
        with self.assertRaisesRegex(EvidenceError,"INVALID_ASSESSMENT"):
            self.report(tasks=[{"task_id":"t","owner":"User","stage":"S3","assessment":assessment}])

    def test_nested_raw_reasoning_cannot_enter_bundle(self):
        assessment=self.sample();assessment["layers"]["STATIC_GEOMETRY"]["controls"]["hidden_reasoning"]="never serialize"
        with self.assertRaisesRegex(EvidenceError,"INVALID_ASSESSMENT"):
            self.report(tasks=[{"task_id":"t","owner":"User","stage":"S3","assessment":assessment}])

    def test_stale_report_evidence_refuses_writing(self):
        assessment=self.sample()
        self.write("verification/positive/receipt.json",b"changed")
        with self.assertRaisesRegex(EvidenceError,"STALE_FILE_HASH"):
            self.report(tasks=[{"task_id":"t","owner":"User","stage":"S3","assessment":assessment}])
        self.assertFalse((self.root/"daily/report").exists())

    def test_artifact_change_after_assessment_is_rejected_by_report(self):
        assessment=self.sample()
        self.write("verification/target/artifact.json",b'{"collision_count":0}')
        with self.assertRaisesRegex(EvidenceError,"STALE_FILE_HASH"):
            self.report(tasks=[{"task_id":"t","owner":"User","stage":"S3","assessment":assessment}])
        self.assertFalse((self.root/"daily/report").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)

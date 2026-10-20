"""Bounded CPU STATIC_GEOMETRY controls; no models, DB, research writes or GPU.

The caller selects an already accepted task from its own registry.  This module
only reads that task and writes a fresh UUID directory under system.runtime.
It does not reaccept/reopen the historical task or inherit its PASS for new data.
"""
import os
import importlib.util
import inspect
from pathlib import Path
import re
import time
import uuid
from . import appcontainer, scene, winproc
from .integrity import canonical, digest, manifest, no_links, read_json, write_json

CONTROLLER_SHA256 = digest(Path(__file__).read_bytes())

LEVEL = "STATIC_GEOMETRY"
CHECKS = frozenset({"reopened_by_usd", "z_up_metres", "meshes_present_nonempty_finite",
    "every_mesh_has_collider", "tread_count_matches_family", "every_rise_within_envelope",
    "first_and_last_rise_within_envelope", "footprint_matches_candidate",
    "fits_room_with_clearance", "traversal_path_reaches_rise"})
LIMITS = ["CollisionAPI presence only: collider enablement, cooking and contact queries are UNVERIFIED.",
    "No scene overlay/placement, obstacle intersection or multi-storey connection is verified.",
    "No native physics, robot climbability, GPU experiment or batch completeness is verified."]

# Fixed program supplied by this versioned module, never by a model or task input.
# It receives exactly one attempt-owned output directory as argv[1].  LPAC can
# write only that directory; the copied interpreter/dependencies are read-only.
REMOVE_COLLISION_PROGRAM = r'''
import hashlib,json,sys
from pathlib import Path
from pxr import Usd,UsdGeom,UsdPhysics
out=Path(sys.argv[1]);path=out/"stair.usda"
stage=Usd.Stage.Open(str(path))
if stage is None:raise RuntimeError("USD_OPEN_FAILED")
def geometry():
    rows=[]
    for p in stage.Traverse():
        if p.IsA(UsdGeom.Mesh):
            m=UsdGeom.Mesh(p)
            rows.append([str(p.GetPath()),str(m.GetPointsAttr().Get()),
                         str(m.GetFaceVertexCountsAttr().Get()),str(m.GetFaceVertexIndicesAttr().Get())])
    return hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(",",":")).encode()).hexdigest(),len(rows)
before,count=geometry();removed=0
for p in stage.Traverse():
    if p.IsA(UsdGeom.Mesh) and p.HasAPI(UsdPhysics.CollisionAPI):
        if not p.RemoveAPI(UsdPhysics.CollisionAPI):raise RuntimeError("API_REMOVAL_FAILED")
        removed+=1
after,count_after=geometry()
if not count or removed!=count or count_after!=count or before!=after:raise RuntimeError("NOT_A_SINGLE_FACTOR_CONTROL")
if any(p.HasAPI(UsdPhysics.CollisionAPI) for p in stage.Traverse() if p.IsA(UsdGeom.Mesh)):
    raise RuntimeError("COLLISION_API_REMAINS")
path.write_text(stage.GetRootLayer().ExportToString(),encoding="utf-8")
(out/"mutation-result.json").write_text(json.dumps({"operation":"remove_mesh_CollisionAPI_only",
    "removed":removed,"mesh_count":count,"geometry_sha256_before":before,
    "geometry_sha256_after":after}),encoding="utf-8")
'''


def _absolute(path):
    if not Path(path).is_absolute():
        raise ValueError("An absolute trusted path is required")
    return appcontainer.safe_path(path)


def _owned(path, root):
    path, root = _absolute(path), _absolute(root)
    if root not in path.parents:
        raise ValueError("Output must stay below this run's private root")
    return path


def baseline(task_dir):
    """Validate immutable historical JSON bindings and the two exact asset files.

    Does not consult/mutate a task database or claim to replay the old review.
    The accepted source manifest is checked internally; the current checker
    source is separately pinned by run_static_geometry.
    """
    task_dir = _absolute(task_dir)
    if str(uuid.UUID(task_dir.name)) != task_dir.name:
        raise ValueError("Expected an exact historical task UUID directory")
    spec, artifact, acceptance, review = (read_json(no_links(task_dir/name)) for name in
        ("spec.json", "artifact.json", "acceptance.json", "review.json"))
    source = spec["source"]
    binding = digest(canonical({"spec": spec, "artifact": artifact}))
    if (spec["id"] != task_dir.name or artifact["task_id"] != spec["id"]
            or artifact["input_sha256"] != spec["input_sha256"]
            or spec["input_sha256"] != digest(canonical(spec["input"]))
            or source["sha256"] != digest(canonical(source["files"]))
            or artifact["source_sha256"] != source["sha256"]
            or acceptance["source_sha256"] != source["sha256"]
            or acceptance["artifact_sha256"] != digest(canonical(artifact))
            or acceptance["binding_sha256"] != binding
            or review["review"] != {"task_id": spec["id"], "binding_sha256": binding,
                                    "verdict": "PASS", "issues": []}
            or review["call_id"] != acceptance["review_call"]
            or not artifact["checks"] or not all(v is True for v in artifact["checks"].values())):
        raise ValueError("Historical acceptance bindings do not match")
    work = no_links(spec["workdir"])
    if work != task_dir/"work":
        raise ValueError("Historical workdir is not the exact registered task/work")
    build = [r for r in artifact["tool_runs"] if r["tool"] == "stair.build_usd"]
    checker = [r for r in artifact["tool_runs"] if r["tool"] == "stair.check_usd"]
    if len(build) != 1 or len(checker) != 1 or not all(
            r.get("ok") is True and r.get("exit_code") == 0 for r in [build[0],checker[0]]):
        raise ValueError("Historical build/check was not accepted")
    matches = [rel for rel in build[0]["outputs"] if len(Path(rel).parts) == 3
               and Path(rel).parts[1:] == ("stair.build_usd", "stair.usda")]
    if len(matches) != 1:
        raise ValueError("Expected exactly the registered built stair path")
    asset = _owned(work/matches[0], work)
    files = {}
    for name in ("stair.usda", "traversal_path.json"):
        path = _owned(asset.parent/name, work)
        rel = path.relative_to(work).as_posix()
        sha = digest(path.read_bytes())
        if build[0]["outputs"].get(rel) != sha:
            raise ValueError("Historical asset no longer matches acceptance: " + name)
        files[name] = {"path": str(path), "sha256": sha}
    return {"task_id": spec["id"], "accepted_source_sha256": source["sha256"],
            "artifact_sha256": acceptance["artifact_sha256"], "binding_sha256": binding,
            "params": checker[0]["params"], "files": files,
            "historical_record_sha256": digest(canonical({"spec":spec,"artifact":artifact,
                "acceptance":acceptance,"review":review}))}


class _ToolSystem:
    """Private CPU-tool context; never forwards meta writes to the live task DB."""
    def __init__(self, system, runtime):
        self.root = _absolute(system.root)
        self.runtime = _absolute(runtime)
        self.runtime.mkdir(parents=True, exist_ok=False)
        self.machine = {"python": system.machine.get("python") or os.sys.executable}
        self.policy = {"tool_timeout_seconds": min(300,system.policy.get("tool_timeout_seconds",300)),
                       "tool_memory_mb": min(6144,system.policy.get("tool_memory_mb",6144))}
        self._meta = {}
        self.deadline = time.monotonic()+1200
    def meta(self, key, default=None):return self._meta.get(key,default)
    def set_meta(self, key, value):self._meta[key]=value
    def remaining_timeout(self, seconds):
        left = min(seconds,self.deadline-time.monotonic())
        if left <= 0:raise TimeoutError("STATIC_GEOMETRY_TIME_LIMIT")
        return left


def _negative(system, work, stage, negative, run):
    """LPAC mutates only the fresh negative copy; target runtime is read-only."""
    negative = _owned(negative,work)
    base = _owned(work/run["sandbox"]["base"],work)
    before = appcontainer.hash_tree(base)
    if before != run["sandbox"]["base_sha256"]:
        raise ValueError("Checker runtime changed before negative mutation")
    receipt = {}
    lease = system.runtime/"tool-leases"/(str(uuid.uuid4())+".json")
    with appcontainer.AppContainer(lease,winproc.identity) as box:
        box.protect_readonly(stage)
        box.protect_output(negative)
        (negative/"tmp").mkdir()
        def started(pid,birth):
            if not birth or birth == "UNKNOWN":raise ValueError("Missing process identity")
            box.started(pid,birth);receipt.update(pid=pid,birth=birth)
        rc,_,_,seconds=winproc.run_owned([str(base/"runtime/python.exe"),"-I","-B","-c",
            REMOVE_COLLISION_PROGRAM,str(negative)],"",negative,box.environment(negative/"tmp"),
            system.remaining_timeout(120),started,system.policy["tool_memory_mb"],
            appcontainer_sid=box.sid,appcontainer_capabilities=box.capabilities)
    list(scene._walk(negative))
    if rc != 0 or appcontainer.hash_tree(base) != before:
        raise ValueError("Negative mutation failed; not a valid scientific control")
    mutation=read_json(appcontainer.safe_path(negative/"mutation-result.json"))
    if (type(mutation.get("removed")) is not int or mutation["removed"] <= 0
            or mutation["removed"] != mutation.get("mesh_count")
            or mutation.get("geometry_sha256_before") != mutation.get("geometry_sha256_after")):
        raise ValueError("Negative control changed geometry or removed no CollisionAPI")
    return {"exit_code":rc,"seconds":round(seconds,3),"process":receipt,"lease":str(lease),
            "program_sha256":digest(REMOVE_COLLISION_PROGRAM.encode()),"result":mutation,
            "outputs":{p.relative_to(work).as_posix():digest(p.read_bytes()) for p in scene._walk(negative)}}


def controls_pass(cases):
    """An operational failure is never a scientifically meaningful rejection."""
    if type(cases) is not dict or set(cases) != {"target","positive","negative"}:
        return False
    for name,case in cases.items():
        result, run = case.get("result"), case.get("run")
        if (type(result) is not dict or type(run) is not dict or run.get("ok") is not True
                or type(run.get("exit_code")) is not int or run["exit_code"] != 0
                or type(result.get("checks")) is not dict or set(result["checks"]) != CHECKS
                or any(type(v) is not bool for v in result["checks"].values())
                or not run.get("process",{}).get("pid") or not run["process"].get("birth")
                or run["process"]["birth"] == "UNKNOWN"):
            return False
        expected = {key: name != "negative" or key != "every_mesh_has_collider" for key in CHECKS}
        if result["checks"] != expected:
            return False
    return cases["target"]["result"] == cases["positive"]["result"] and (
        cases["target"]["result"]["measured"] == cases["negative"]["result"]["measured"])


def _source_copy(system, work, source):
    from . import evidence
    actual = Path(inspect.getsourcefile(scene.run_tool)).resolve()
    if actual != (system.root/"researchops/scene.py").resolve():
        raise ValueError("Loaded scene adapter does not match the declared source root")
    rows=[]
    for rel,sha in source["files"].items():
        dest=work/"source/project"/rel
        if appcontainer.copy_file_checked(system.root/rel,dest) != sha:
            raise ValueError("Source changed while copying")
        rows.append({"path":dest.relative_to(work).as_posix(),"sha256":sha})
    for original,name,sha in [(Path(__file__),"checker.py",CONTROLLER_SHA256),
                             (Path(evidence.__file__),"evaluator.py",evidence.EVALUATOR_SHA256)]:
        dest=work/"source"/name
        if appcontainer.copy_file_checked(original,dest) != sha:
            raise ValueError("Loaded controller/evaluator source changed")
        rows.append({"path":dest.relative_to(work).as_posix(),"sha256":sha})
    return rows


def static_checker(store, run):
    """Pure scientific reading of one independently recorded real checker result."""
    from .evidence import Observation
    matches=[ref for ref in run.binding.artifacts if ref.path.endswith("/stair.check_usd/result.json")]
    if len(matches)!=1:return Observation("BLOCKED","INVALID_RESULT")
    envelope=store.json(matches[0])
    if type(envelope) is not dict or set(envelope)!={"ok","result"} or envelope["ok"] is not True:
        return Observation("BLOCKED","INVALID_RESULT")
    result=envelope["result"]
    if (type(result) is not dict or type(result.get("checks")) is not dict
            or set(result["checks"])!=CHECKS or any(type(v) is not bool for v in result["checks"].values())):
        return Observation("BLOCKED","INVALID_RESULT")
    if all(result["checks"].values()):return Observation("PASS","STATIC_GEOMETRY_VALID")
    if result["checks"]=={key:key!="every_mesh_has_collider" for key in CHECKS}:
        return Observation("FAIL","MISSING_COLLISION_API")
    return Observation("FAIL","STATIC_GEOMETRY_INVALID")


def reconstruct_assessment(store, bundle):
    """Revalidate files/owned leases/inputs/source, then mint a fresh Assessment.

    A persisted assessment or `process_verified=True` is never accepted as input.
    The checker is imported only from the exact copy of this already loaded
    versioned module, not from arbitrary bundle-supplied Python.
    """
    from . import evidence
    from .evidence import (EvidenceError, FileRef, Binding, TrustedRun, RegisteredChecker,
                           GateContract, evaluate_gate)
    if not isinstance(bundle,FileRef):raise EvidenceError("INVALID_BUNDLE_REFERENCE")
    report=store.json(bundle,limit=4*1024*1024)
    work=store.path(bundle.path).parent
    if Path(report.get("workdir",""))!=work or bundle.path.split("/")[-1]!="report.json":
        raise EvidenceError("CONTROL_WORKDIR_MISMATCH")
    if report.get("status")!="PASS" or report.get("passed") is not True or report.get("level")!=LEVEL:
        raise EvidenceError("CONTROL_SET_NOT_PASSED")
    old=baseline(store.runtime/"tasks"/report["baseline"]["task_id"])
    if old!=report["baseline"]:raise EvidenceError("STALE_HISTORICAL_BASELINE")
    prefix=work.relative_to(store.runtime).as_posix()+"/"
    def ref(rel,sha=None):
        if type(rel) is not str or not rel.startswith(("source/","assets/","check-","control-")):
            raise EvidenceError("CONTROL_REFERENCE_SCOPE")
        value=store.fingerprint(prefix+rel)
        if sha is not None and value.sha256!=sha:raise EvidenceError("STALE_CONTROL_HASH")
        return value
    source_rows=report["source_files"]
    source=tuple(ref(row["path"],row["sha256"]) for row in source_rows)
    if len(source)!=len(set(r.path for r in source)):
        raise EvidenceError("DUPLICATE_SOURCE_REFERENCE")
    copied={row["path"].removeprefix("source/project/"):row["sha256"] for row in source_rows
            if row["path"].startswith("source/project/")}
    if digest(canonical(copied))!=report["source_sha256"]:
        raise EvidenceError("SOURCE_MANIFEST_MISMATCH")
    checker=ref("source/checker.py",CONTROLLER_SHA256)
    evaluator=ref("source/evaluator.py",evidence.EVALUATOR_SHA256)
    if checker not in source or evaluator not in source or digest(Path(__file__).read_bytes())!=CONTROLLER_SHA256:
        raise EvidenceError("CHECKER_SOURCE_MISMATCH")
    if not controls_pass(report.get("cases")):
        raise EvidenceError("CONTROL_CONTENT_INVALID")
    runs={}
    runtime_closure=set()
    for role in ("target","positive","negative"):
        saved=report["cases"][role]
        receipt=ref("control-receipts/"+role+".json",saved["receipt_sha256"])
        run=store.json(receipt)
        if run!=saved["run"] or run.get("tool")!="stair.check_usd" or run.get("runner")!="stair_check":
            raise EvidenceError("CONTROL_RECEIPT_MISMATCH")
        if run.get("params")!=old["params"] or run.get("ok") is not True or type(run.get("exit_code")) is not int or run["exit_code"]!=0:
            raise EvidenceError("CONTROL_PROCESS_FAILED")
        stage=work/("check-"+role);out=stage/"stair.check_usd"
        sandbox=run["sandbox"]
        base=_owned(work/sandbox["base"],stage)
        inputs=_owned(work/sandbox["inputs"],stage)
        if (base!=stage/"_sandbox/base" or inputs!=stage/"_sandbox/inputs-stair.check_usd"
                or appcontainer.hash_tree(base)!=sandbox["base_sha256"]
                or appcontainer.hash_tree(inputs)!=sandbox["input_sha256"]
                or digest((base/"scene_runner.py").read_bytes())!=copied.get("researchops/scene_runner.py")):
            raise EvidenceError("STALE_EXECUTION_SANDBOX")
        runtime_closure.add(sandbox["base_sha256"])
        expected_prefix=(out.relative_to(work).as_posix()+"/")
        if not run["outputs"] or any(not p.startswith(expected_prefix) for p in run["outputs"]):
            raise EvidenceError("CONTROL_OUTPUT_SCOPE")
        if set(run["outputs"])!={p.relative_to(work).as_posix() for p in scene._walk(out)}:
            raise EvidenceError("CONTROL_OUTPUT_SET_CHANGED")
        artifacts=tuple(ref(p,sha) for p,sha in run["outputs"].items())
        process=run.get("process",{})
        if (type(process.get("pid")) is not int or process["pid"]<=0 or not str(process.get("birth","")).isdigit()
                or read_json(no_links(out/"process.json"))!={**process,"tool":"stair.check_usd"}):
            raise EvidenceError("PROCESS_IDENTITY_INVALID")
        if str(uuid.UUID(sandbox["lease"][:-5]))+".json"!=sandbox["lease"]:
            raise EvidenceError("CONTROL_LEASE_INVALID")
        lease_ref=ref("control-runtime/tool-leases/"+sandbox["lease"])
        lease=store.json(lease_ref)
        if (lease.get("state")!="CLOSED" or lease.get("child")!=process
                or not re.fullmatch(r"BGV\.Tool\.[0-9a-f]{32}",lease.get("name",""))
                or lease.get("network_capabilities")!=[] or lease.get("capabilities")!=["registryRead"]
                or lease.get("recovered") is True):
            raise EvidenceError("CONTROL_OWNER_LEASE_INVALID")
        identity=winproc.identity(process["pid"])
        if identity=="UNKNOWN" or identity==process["birth"]:
            raise EvidenceError("CONTROL_PROCESS_NOT_CONFIRMED_EXITED")
        request=read_json(no_links(out/"request.json"))
        if request!={"tool":"stair_check","params":old["params"],"inputs":{"stair_usda":str(inputs/"stair.usda")},
                      "out_dir":str(out),"buildingsgen_src":str(base/"src")}:
            raise EvidenceError("CONTROL_REQUEST_MISMATCH")
        case_inputs=tuple(ref("assets/"+role+"/"+name) for name in ("stair.usda","traversal_path.json"))
        for item in case_inputs:
            name=Path(item.path).name
            if digest((inputs/name).read_bytes())!=item.sha256:
                raise EvidenceError("COPIED_INPUT_MISMATCH")
            if (name=="traversal_path.json" or role!="negative") and item.sha256!=old["files"][name]["sha256"]:
                raise EvidenceError("CONTROL_BASELINE_MISMATCH")
        result=store.json(next(r for r in artifacts if r.path.endswith("/result.json")))
        if result!={"ok":True,"result":saved["result"]}:
            raise EvidenceError("CONTROL_RESULT_MISMATCH")
        run_id=role+"-"+str(uuid.UUID(work.name))
        runs[role]=TrustedRun(run_id,"stair.check_usd",receipt,
            Binding(source,case_inputs,artifacts+(lease_ref,)),(old["task_id"],),(),role,True,0,True)
    if len(runtime_closure)!=1:
        raise EvidenceError("CONTROL_RUNTIME_CLOSURE_DIFFERS")
    mutation=report["mutation"]
    if (mutation.get("exit_code")!=0 or mutation.get("program_sha256")!=digest(REMOVE_COLLISION_PROGRAM.encode())
            or mutation["result"].get("removed")!=report["cases"]["negative"]["result"]["measured"]["mesh_count"]
            or mutation["result"].get("geometry_sha256_before")!=mutation["result"].get("geometry_sha256_after")):
        raise EvidenceError("NEGATIVE_MUTATION_NOT_VERIFIED")
    for p,sha in mutation["outputs"].items():ref(p,sha)
    mut_lease=_owned(Path(mutation["lease"]),work/"control-runtime")
    mut_owner=read_json(mut_lease)
    mut_child=mutation.get("process",{})
    if (mut_owner.get("state")!="CLOSED" or mut_owner.get("child")!=mut_child
            or mut_owner.get("network_capabilities")!=[] or mut_owner.get("capabilities")!=["registryRead"]
            or mut_owner.get("recovered") is True
            or type(mut_child.get("pid")) is not int or not str(mut_child.get("birth","")).isdigit()
            or winproc.identity(mut_child["pid"]) in ("UNKNOWN",mut_child["birth"])):
        raise EvidenceError("NEGATIVE_MUTATION_OWNER_INVALID")
    module_name="researchops._fixed_science_"+uuid.uuid4().hex
    module_spec=importlib.util.spec_from_file_location(module_name,store.path(checker.path))
    module=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(module)
    registered=RegisteredChecker("stair.check_usd",module.static_checker,checker,
        layers=(LEVEL,),scientific_reasons=("STATIC_GEOMETRY_VALID","MISSING_COLLISION_API","STATIC_GEOMETRY_INVALID"))
    contract=GateContract("static-cpu-controls",old["task_id"],LEVEL,"stair.check_usd",
        runs["target"],runs["positive"],runs["negative"],"MISSING_COLLISION_API",(old["task_id"],),"deterministic",())
    return evaluate_gate(store,contract,{r.run_id:r for r in runs.values()},{registered.checker_id:registered})


def run_static_geometry(system, accepted_task_dir):
    """Run one bounded deterministic control set; result remains STATIC_GEOMETRY.

    No model is called, no task is enqueued, no research run is resumed.  Inputs
    to the fixed checker come only from the validated historical acceptance.
    Operational failures preserve evidence and return NEEDS_ATTENTION.
    """
    historical = baseline(accepted_task_dir)
    source = manifest(system.root)
    runtime = _absolute(system.runtime)
    work = _owned(runtime/"science-runs"/str(uuid.uuid4()),runtime)
    work.mkdir(parents=True,exist_ok=False)
    context = _ToolSystem(system,work/"control-runtime")
    report = {"schema":1,"level":LEVEL,"status":"NEEDS_ATTENTION","passed":False,
        "source_sha256":source["sha256"],"baseline":historical,"workdir":str(work),
        "model_calls":0,"gpu":False,"remote":False,"cases":{},"limitations":LIMITS}
    write_json(work/"report.json",report)
    try:
        report["source_files"]=_source_copy(system,work,source)
        inputs={}
        for name in ("target","positive","negative"):
            directory=_owned(work/"assets"/name,work);directory.mkdir(parents=True)
            for file,entry in historical["files"].items():
                if appcontainer.copy_file_checked(entry["path"],directory/file) != entry["sha256"]:
                    raise ValueError("Baseline changed while copying")
            inputs[name]=directory/"stair.usda"
        spec={"workdir":str(work)}
        params=historical["params"]
        tool=scene.registry(system.root)[0]["tools"]["stair.check_usd"]
        scene.validate_params(tool,params)
        stage=_owned(work/"check-target",work)
        result,run=scene.run_tool(context,spec,"stair.check_usd",params,stage,{"stair_usda":str(inputs["target"])})
        report["cases"]["target"]={"result":result,"run":run}
        write_json(work/"control-receipts/target.json",run)
        report["cases"]["target"]["receipt_sha256"]=digest((work/"control-receipts/target.json").read_bytes())
        write_json(work/"report.json",report)
        report["mutation"]=_negative(context,work,stage,inputs["negative"].parent,run)
        for name in ("positive","negative"):
            result,run=scene.run_tool(context,spec,"stair.check_usd",params,_owned(work/("check-"+name),work),
                                      {"stair_usda":str(inputs[name])})
            report["cases"][name]={"result":result,"run":run}
            write_json(work/"control-receipts"/(name+".json"),run)
            report["cases"][name]["receipt_sha256"]=digest((work/"control-receipts"/(name+".json")).read_bytes())
            write_json(work/"report.json",report)
        report["asset_sha256"]={name:digest(path.read_bytes()) for name,path in inputs.items()}
        report["baseline_unchanged"] = baseline(accepted_task_dir) == historical
        report["source_unchanged"] = manifest(system.root) == source
        passed=(controls_pass(report["cases"]) and report["baseline_unchanged"] and report["source_unchanged"]
                and report["asset_sha256"]["target"] == report["asset_sha256"]["positive"]
                == historical["files"]["stair.usda"]["sha256"]
                and report["asset_sha256"]["negative"] != report["asset_sha256"]["target"])
        report.update(passed=passed,status="PASS" if passed else "NEEDS_ATTENTION",
            negative_reason="MISSING_COLLISION_API_DETECTED" if passed else "CONTROL_SET_REJECTED")
    except Exception as exc:
        # Do not retain arbitrary exception strings/stdout that might include data.
        report.update(status="NEEDS_ATTENTION",error_type=type(exc).__name__,error="CONTROL_EXECUTION_FAILED")
    finally:
        report["report_path"]=str(work/"report.json")
        write_json(work/"report.json",report)
    return report

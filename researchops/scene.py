"""Registered scene tools and skills for the humanoid scene workflow.

Tools are fixed adapters (researchops/scene_runner.py) with schema-checked parameters, pinned
external bindings and outputs confined to the task's own stage directory. A skill fixes the tool
order, the single model step and the acceptance rules. A model may only choose among values the
orchestrator computed; it never supplies a command, a path or a tool.
"""
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import sys
import uuid
from . import appcontainer, winproc
from .integrity import canonical, digest, no_links, read_json, write_json

ACTION = "scene_stair_workflow"
SELECTION_KEYS = {"task_id", "input_sha256", "source_sha256", "template", "rationale"}
ARTIFACT_KEYS = {"task_id", "input_sha256", "source_sha256", "skill", "selection", "inventory", "candidates",
                 "tool_runs", "checks", "measured", "not_verified", "bindings"}


class ToolFailure(Exception):
    """A registered tool did not complete; the stage needs attention, never a blind retry."""


class NoFit(Exception):
    """Every candidate was measured and none fits; the report is kept, no model is called."""


def registry(root):
    return read_json(Path(root)/"config/tools.json"), read_json(Path(root)/"config/skills.json")


def _walk(path, suffixes=None):
    path = appcontainer.safe_path(path)
    for base, dirs, names in os.walk(path):
        dirs[:] = sorted(d for d in dirs if d not in ("__pycache__", ".git"))
        for d in dirs:
            appcontainer.safe_path(Path(base)/d)
        for name in sorted(names):
            if suffixes is None or name.endswith(tuple(suffixes)):
                yield appcontainer.safe_path(Path(base)/name)


def tree_sha256(path, suffixes=None):
    """Content hash of an external tree (relative paths and file bytes)."""
    path = Path(path)
    return digest(canonical({p.relative_to(path).as_posix(): digest(p.read_bytes()) for p in _walk(path, suffixes)}))


def listing_sha256(path):
    """Names, sizes and mtimes; used to prove a tool run wrote nothing into a read-only tree."""
    path = Path(path)
    rows = []
    for p in _walk(path):
        st = p.stat()
        rows.append([p.relative_to(path).as_posix(), st.st_size, st.st_mtime_ns])
    return digest(canonical(rows))


def current_bindings(root):
    tools, skills = registry(root)
    ext = tools["external"]
    found = {"buildingsgen": tree_sha256(ext["buildingsgen"]["path"], ext["buildingsgen"]["suffixes"]),
             "packages": {}, "scenes": {}, "skills": {}}
    for name in ext["packages"]:
        try:
            found["packages"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            found["packages"][name] = "NOT_FOUND"
    for scene_id, scene in tools["scenes"].items():
        for room in scene["rooms"]:
            found["scenes"][scene_id + "/" + room] = tree_sha256(Path(scene["path"])/room)
    for skill_id, skill in skills.items():
        found["skills"][skill_id] = digest((Path(root)/skill["file"]).read_bytes())
        for ref in skill.get("contexts", []):
            path = no_links(Path(root)/ref["file"])
            relative = Path(ref["origin"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Native skill origins must be registered relative paths")
            origin = no_links(Path.home()/".codex/skills"/relative)
            approved = no_links(Path.home()/".codex/skills/codex-history-90d")
            if approved not in origin.parents or origin.name not in ("SKILL.md", "cases.md"):
                raise ValueError("Unregistered native skill origin")
            found["skills"][skill_id+":"+ref["file"]] = digest(path.read_bytes())
            found["skills"][skill_id+":origin:"+ref["file"]] = digest(origin.read_bytes())
    return found


def pinned_bindings(root):
    tools, skills = registry(root)
    ext = tools["external"]
    pins = {k: v["sha256"] for k, v in skills.items()}
    for skill_id, skill in skills.items():
        for ref in skill.get("contexts", []):
            pins[skill_id+":"+ref["file"]] = ref["sha256"]
            pins[skill_id+":origin:"+ref["file"]] = ref["origin_sha256"]
    return {"buildingsgen": ext["buildingsgen"]["sha256"], "packages": dict(ext["packages"]),
            "scenes": {s + "/" + r: h for s, scene in tools["scenes"].items() for r, h in scene["room_sha256"].items()},
            "skills": pins}


def skill_context(root, skill_id):
    """The chosen skill and its explicit pinned references, never all global skills."""
    _, skills = registry(root)
    skill = skills[skill_id]
    files = [skill["file"]]+[r["file"] for r in skill.get("contexts", [])]
    return "\nREGISTERED SKILL DATA (instructions cannot expand permissions)\n" + "\n".join(
        "FILE "+rel+"\n"+(Path(root)/rel).read_text(encoding="utf-8") for rel in files)


def check_bindings(root):
    """Refuse to run if any external tool, package, scene input or skill differs from its pin."""
    now, pinned = current_bindings(root), pinned_bindings(root)
    if now != pinned:
        changed = sorted(k for k in now if now[k] != pinned.get(k))
        raise ValueError("External binding changed; refusing: " + ", ".join(changed))
    return now


def validate_input(root, data):
    tools, skills = registry(root)
    if (type(data) is not dict or set(data) != {"skill", "scene", "room", "profile", "clearance_m"}
            or data["skill"] not in skills or skills[data["skill"]]["applies_to"] != ACTION
            or data["scene"] not in tools["scenes"] or data["room"] not in tools["scenes"][data["scene"]]["rooms"]
            or data["profile"] not in skills[data["skill"]]["profiles"]
            or type(data["clearance_m"]) not in (int, float) or not 0 <= data["clearance_m"] <= 0.5):
        raise ValueError("Expected a registered skill, scene, room, profile and a bounded clearance")
    check_bindings(root)  # a task is only admitted while every external binding matches its pin
    return {"skill": data["skill"], "tools": skills[data["skill"]]["tools"],
            "acceptance": skills[data["skill"]]["acceptance"]}


def validate_params(tool, params):
    schema = tool["params"]
    if type(params) is not dict or set(params) != set(schema):
        raise ValueError("Tool parameters do not match the registered schema")
    for key, rule in schema.items():
        value = params[key]
        if "enum" in rule and value not in rule["enum"]:
            raise ValueError("Parameter outside its enum: " + key)
        if rule.get("type") == "number" and (type(value) not in (int, float) or not rule["min"] <= value <= rule["max"]):
            raise ValueError("Parameter outside its range: " + key)
        if rule.get("type") == "integer" and (type(value) is not int or not rule["min"] <= value <= rule["max"]):
            raise ValueError("Parameter outside its range: " + key)
        if rule.get("type") == "pair" and (type(value) is not list or len(value) != 2 or not all(
                type(v) in (int, float) and rule["min"] <= v <= rule["max"] for v in value)):
            raise ValueError("Parameter outside its range: " + key)
        if rule.get("type") == "id" and (type(value) is not str or not value.replace("_", "").replace("-", "").isalnum()):
            raise ValueError("Parameter is not a plain identifier: " + key)


def restore_low_labels(system):
    for path in system.meta("low_labelled", []) or []:
        if Path(path).exists():
            winproc.label_medium(path)
    system.set_meta("low_labelled", [])


def recover_tool_profiles(system):
    """No redispatch and no PID killing: delete only dead, registered tool profiles."""
    base = system.runtime/"tool-leases"
    for path in sorted(base.glob("*.json")) if base.exists() else []:
        appcontainer.recover_lease(no_links(path), winproc.identity)


def prepare_sandbox(system, spec, tools, stage, tool_id, inputs):
    """Copy only registered code/dependencies/data into an attempt-owned read-only tree."""
    sandbox = stage/"_sandbox"
    base = sandbox/"base"
    receipt = sandbox/"base-receipt.json"
    if not base.exists():
        packages = []
        for name in ("numpy", "scipy", "trimesh", "pxr", "yaml", "_yaml"):
            found = importlib.util.find_spec(name)
            if found is None or not found.submodule_search_locations:
                raise ToolFailure("Registered dependency missing: " + name)
            package = no_links(next(iter(found.submodule_search_locations)))
            packages.append(package)
            libs = package.parent/(name+".libs")
            if libs.exists():
                packages.append(no_links(libs))
        python = system.machine.get("python") or sys.executable
        appcontainer.copy_runtime(python, base/"runtime", packages)
        appcontainer.copy_tree_checked(tools["external"]["buildingsgen"]["path"], base/"src/buildingsgen",
                                        ("__pycache__", "tests", "test"),
                                        tuple(tools["external"]["buildingsgen"]["suffixes"]))
        appcontainer.copy_file_checked(system.root/"researchops/scene_runner.py", base/"scene_runner.py")
        write_json(receipt, {"sha256": appcontainer.hash_tree(base)})
    base_hash = read_json(receipt)["sha256"]
    if appcontainer.hash_tree(base) != base_hash:
        raise ToolFailure("Read-only runtime copy changed")
    copied = sandbox/("inputs-"+tool_id)
    copied.mkdir(parents=True)
    mapped = {}
    if tool_id == "scene.room_meshes":
        approved = no_links(Path(tools["scenes"][spec["input"]["scene"]]["path"])/spec["input"]["room"])
        if set(inputs) != {"room_dir"} or no_links(inputs["room_dir"]) != approved:
            raise ValueError("Unregistered room input")
        appcontainer.copy_tree_checked(approved, copied/"room")
        mapped["room_dir"] = str(copied/"room")
    elif tool_id == "stair.check_usd":
        if set(inputs) != {"stair_usda"}:
            raise ValueError("Expected the generated stair asset")
        original, workdir = no_links(inputs["stair_usda"]), no_links(spec["workdir"])
        if original.name != "stair.usda" or workdir not in original.parents:
            raise ValueError("Stair input must be an asset in this task's workdir")
        for name in ("stair.usda", "traversal_path.json"):
            appcontainer.copy_file_checked(no_links(original.parent/name), copied/name)
        mapped["stair_usda"] = str(copied/"stair.usda")
    elif inputs:
        raise ValueError("This tool accepts no file inputs")
    return base, base_hash, copied, appcontainer.hash_tree(copied), mapped


def run_tool(system, spec, tool_id, params, stage_dir, inputs=None):
    """Run one registered tool in its own owned process; return (result, run record)."""
    tools, _ = registry(system.root)
    if tool_id not in tools["tools"]:
        raise ValueError("Unregistered tool: " + tool_id)
    tool = tools["tools"][tool_id]
    validate_params(tool, params)
    bindings = check_bindings(system.root)
    workdir = no_links(spec["workdir"])
    out = no_links(Path(stage_dir)/tool_id)
    if workdir not in out.parents:
        raise ValueError("Tool output must stay inside the task workdir")
    out.mkdir(parents=True)
    stage = no_links(stage_dir)
    restore_low_labels(system)  # legacy migration only; new tools never use Low labels
    recover_tool_profiles(system)
    (out/"tmp").mkdir()
    guarded = [tools["external"]["buildingsgen"]["repository"]] + [
        str(Path(s["path"])/r) for s in tools["scenes"].values() for r in s["rooms"]]
    before = [listing_sha256(g) for g in guarded]
    identity = {}
    lease = system.runtime/"tool-leases"/(str(uuid.uuid4())+".json")
    try:
        base, base_hash, copied, input_hash, mapped = prepare_sandbox(system, spec, tools, stage, tool_id, inputs or {})
        request = {"tool": tool["runner"], "params": params, "inputs": mapped, "out_dir": str(out),
                   "buildingsgen_src": str(base/"src")}
        write_json(out/"request.json", request)
        argv = [str(base/"runtime/python.exe"), "-I", "-B", str(base/"scene_runner.py"), str(out/"request.json")]
        with appcontainer.AppContainer(lease, winproc.identity) as box:
            box.protect_readonly(stage)  # includes ancestors owned by this execution, no external ACL mutation
            box.protect_output(out)

            def started(pid, birth):
                if not birth or birth == "UNKNOWN":
                    raise ToolFailure("Cannot establish tool process identity")
                box.started(pid, birth)
                identity.update(pid=pid, birth=birth)
                write_json(out/"process.json", {"pid": pid, "birth": birth, "tool": tool_id})

            rc, _, _, seconds = winproc.run_owned(argv, "", out, box.environment(out/"tmp"),
                system.remaining_timeout(system.policy["tool_timeout_seconds"]), started,
                system.policy["tool_memory_mb"], appcontainer_sid=box.sid,
                appcontainer_capabilities=box.capabilities)
        if appcontainer.hash_tree(base) != base_hash or appcontainer.hash_tree(copied) != input_hash:
            raise ToolFailure("Read-only execution copy changed")
        check_bindings(system.root)
    finally:
        if [listing_sha256(g) for g in guarded] != before:  # evaluated even when the run raised
            raise ToolFailure("Read-only research input changed during " + tool_id)
    list(_walk(out))  # vet every directory/file before reading any child-created output
    result = read_json(appcontainer.safe_path(out/"result.json")) if (out/"result.json").exists() else {"ok": False, "error": "NO_RESULT"}
    outputs = {p.relative_to(workdir).as_posix(): digest(p.read_bytes()) for p in _walk(out)}
    run = {"tool": tool_id, "runner": tool["runner"], "params": params, "exit_code": rc,
           "seconds": round(seconds, 3), "ok": bool(result.get("ok")) and rc == 0, "process": identity,
           "outputs": outputs, "bindings": {k: bindings[k] for k in tool["bindings"]},
           "sandbox": {"base": base.relative_to(workdir).as_posix(), "base_sha256": base_hash,
                       "inputs": copied.relative_to(workdir).as_posix(), "input_sha256": input_hash,
                       "lease": lease.name}}
    if not run["ok"]:
        write_json(out/"run.json", {**run, "error": result.get("error")})
        raise ToolFailure(tool_id + " failed")
    return result["result"], run


def selection_schema(spec, fitting):
    props = {k: {"type": "string"} for k in ("task_id", "input_sha256", "source_sha256")}
    props["template"] = {"type": "string", "enum": fitting}
    props["rationale"] = {"type": "array", "items": {"type": "string"}}
    return {"type": "object", "properties": props, "required": sorted(SELECTION_KEYS), "additionalProperties": False}


def valid_selection(spec, value, fitting):
    return (type(value) is dict and set(value) == SELECTION_KEYS and value["task_id"] == spec["id"]
            and value["input_sha256"] == spec["input_sha256"] and value["source_sha256"] == spec["source"]["sha256"]
            and value["template"] in fitting and type(value["rationale"]) is list and 1 <= len(value["rationale"]) <= 6
            and all(type(r) is str and 10 <= len(r) <= 400 for r in value["rationale"]))


def execute_stage(system, spec):
    """Skill-ordered run: inventory -> candidates -> model selection -> build -> check.

    Returns (artifact or None, model evidence, call id, all checks passed)."""
    data = spec["input"]
    tools, skills = registry(system.root)
    skill = skills[data["skill"]]
    scene = tools["scenes"][data["scene"]]
    stage = Path(spec["workdir"])/("exec-" + uuid.uuid4().hex[:12])  # fresh, single-writer per execution
    order = skill["tools"]
    inv, r1 = run_tool(system, spec, order[0], {"scene": data["scene"], "room": data["room"]}, stage,
                       {"room_dir": str(Path(scene["path"])/data["room"])})
    params = {"profile": data["profile"], "rise_m": inv["wall_height_m"], "room_interior_m": inv["interior_m"],
              "clearance_m": data["clearance_m"]}
    cand, r2 = run_tool(system, spec, order[1], params, stage)
    fitting = [c["family"] for c in cand["candidates"] if c.get("fits_room")]
    if not fitting:
        # A deterministic negative result: recorded, and no model is asked to choose among nothing.
        write_json(stage/"no-fit-report.json", {"task_id": spec["id"], "room": inv, "candidates": cand,
                                                "tool_runs": [r1, r2]})
        raise NoFit("No registered stair template fits this room")
    prompt = ((system.root/"prompts/scene_select.txt").read_text(encoding="utf-8")
              + skill_context(system.root, data["skill"]) + "\nTASK DATA\n" + canonical({
        "task_id": spec["id"], "input_sha256": spec["input_sha256"], "source_sha256": spec["source"]["sha256"],
        "room": {k: inv[k] for k in ("floor_extent_m", "interior_m", "wall_height_m", "wall_thickness_m", "assumptions")},
        "candidates": cand, "fitting_templates": fitting,
        "project_context": system.project_context(spec),
        "review_feedback": system.review_feedback(spec)}).decode())
    selection, meta, call_id = system.call(spec, "execute", spec["writer"], prompt, selection_schema(spec, fitting),
                                           lambda value: valid_selection(spec, value, fitting))
    if selection is None:
        return None, meta, call_id, False
    chosen = next(c for c in cand["candidates"] if c["family"] == selection["template"])
    build, r3 = run_tool(system, spec, order[2], {"profile": data["profile"], "rise_m": inv["wall_height_m"],
                                                  "family": selection["template"]}, stage)
    check, r4 = run_tool(system, spec, order[3], {
        **params, "family": selection["template"], "expected_tread_count": chosen["spec"]["authored_tread_count"],
        "expected_footprint_m": chosen["footprint_sorted_m"]}, stage,
        {"stair_usda": str(stage/order[2]/"stair.usda")})
    artifact = {"task_id": spec["id"], "input_sha256": spec["input_sha256"], "source_sha256": spec["source"]["sha256"],
                "skill": {"id": data["skill"], "sha256": digest((system.root/skill["file"]).read_bytes())},
                "selection": selection,
                "inventory": {k: inv[k] for k in ("floor_extent_m", "interior_m", "wall_height_m", "wall_thickness_m")},
                "candidates": [{k: c.get(k) for k in ("family", "designed", "fits_room", "footprint_sorted_m",
                                                      "library_footprint_sorted_m", "margin_m")}
                               for c in cand["candidates"]],
                "tool_runs": [r1, r2, r3, r4],
                "checks": {**{"room_" + k: v for k, v in inv["checks"].items()}, **check["checks"]},
                "measured": check["measured"],
                "not_verified": check["not_verified"], "bindings": check_bindings(system.root)}
    return artifact, meta, call_id, all(artifact["checks"].values())


def valid_artifact(system, spec, artifact):
    """Deterministic acceptance from disk: every recorded output still hashes the same, every
    check passed, the selection was a fitting template, and all bindings are still pinned."""
    try:
        if type(artifact) is not dict or set(artifact) != ARTIFACT_KEYS:
            return False
        if (artifact["task_id"] != spec["id"] or artifact["input_sha256"] != spec["input_sha256"]
                or artifact["source_sha256"] != spec["source"]["sha256"]):
            return False
        _, skills = registry(system.root)
        skill = skills[spec["input"]["skill"]]
        fitting = [c["family"] for c in artifact["candidates"] if c["fits_room"] is True]
        workdir = Path(spec["workdir"])
        runs = artifact["tool_runs"]
        if (artifact["skill"] != {"id": spec["input"]["skill"], "sha256": digest((system.root/skill["file"]).read_bytes())}
                or not valid_selection(spec, artifact["selection"], fitting)
                or [r["tool"] for r in runs] != skill["tools"] or not all(r["ok"] and r["exit_code"] == 0 for r in runs)
                or artifact["bindings"] != check_bindings(system.root)
                or not artifact["checks"] or not all(v is True for v in artifact["checks"].values())
                or len(canonical(artifact)) > system.policy["max_artifact_bytes"]):
            return False
        tools, _ = registry(system.root)
        stage = workdir/next(iter(runs[0]["outputs"])).split("/")[0]
        for run, tool_id in zip(runs, skill["tools"]):
            prefix = stage.name + "/" + tool_id + "/"
            required = {prefix + name for name in tools["tools"][tool_id]["outputs"]}
            if not required <= set(run["outputs"]) or not all(rel.startswith(prefix) for rel in run["outputs"]):
                return False  # every registered output present, nothing recorded outside the run's directory
            on_disk = {p.relative_to(workdir).as_posix() for p in _walk(stage/tool_id)}
            if on_disk != set(run["outputs"]):
                return False  # no file added or removed after the run
            for rel, sha in run["outputs"].items():
                path = no_links(workdir/rel)
                if workdir not in path.parents or digest(path.read_bytes()) != sha:
                    return False
            sandbox = run["sandbox"]
            for key, hash_key in (("base", "base_sha256"), ("inputs", "input_sha256")):
                path = no_links(workdir/sandbox[key])
                if stage/"_sandbox" not in path.parents or appcontainer.hash_tree(path) != sandbox[hash_key]:
                    return False
            if str(uuid.UUID(sandbox["lease"][:-5]))+".json" != sandbox["lease"]:
                return False
            lease = read_json(no_links(system.runtime/"tool-leases"/sandbox["lease"]))
            if lease.get("state") != "CLOSED" or lease.get("child") != run["process"]:
                return False
        inv, cand, _, check = (read_json(stage/t/"result.json")["result"] for t in skill["tools"])
        derived = [{k: c.get(k) for k in ("family", "designed", "fits_room", "footprint_sorted_m",
                                          "library_footprint_sorted_m", "margin_m")} for c in cand["candidates"]]
        return (artifact["checks"] == {**{"room_" + k: v for k, v in inv["checks"].items()}, **check["checks"]}
                and artifact["inventory"] == {k: inv[k] for k in ("floor_extent_m", "interior_m", "wall_height_m", "wall_thickness_m")}
                and artifact["candidates"] == derived and artifact["measured"] == check["measured"]
                and artifact["not_verified"] == check["not_verified"]
                and runs[1]["params"]["rise_m"] == inv["wall_height_m"] and runs[1]["params"]["room_interior_m"] == inv["interior_m"])
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        return False

"""Absolute-path command entry; scripts never execute model-supplied commands."""
import argparse
import json
import os
from pathlib import Path
import sys
from researchops.core import System, REPO, OWNER, TASK_NAME, verify_repo
from researchops.deployment import (authorize_cycle, close_cycle, independent_review, freeze, verified_acceptance,
                                    resume_source_audit, verify_activation)
from researchops.integrity import (read_json, no_links, manifest, digest, canonical,
                                   CREDENTIAL_NAMES, CREDENTIAL_PREFIXES, CREDENTIAL_SUFFIXES)
from researchops import scene


def guarded_file(path, limit):
    path = no_links(path)
    name = path.name.lower()
    if (name in CREDENTIAL_NAMES or name.startswith(CREDENTIAL_PREFIXES)
            or name.endswith(CREDENTIAL_SUFFIXES) or path.stat().st_size > limit):
        raise ValueError("Sensitive or oversized request refused before reading")
    return path


def request_file(path, limit=32768):
    return read_json(guarded_file(path, limit))


def authorization_file(path):
    return guarded_file(path, 20000).read_text(encoding="utf-8-sig")


def governance_command(system, args):
    from researchops import projects, planning
    if args.cmd == "projects":
        return projects.status_cards(system)
    if args.cmd == "project-show":
        return projects.get_project(system, args.project)
    if args.cmd == "project-register":
        data = request_file(args.file)
        if type(data) is not dict or set(data)-{"id", "name", "profile", "rules_text", "allowed_actions", "readonly_roots", "kind"}:
            raise ValueError("Unknown project request fields")
        return projects.register_project(system, data["id"], data["name"], data["profile"], data["rules_text"],
            data["allowed_actions"], data.get("readonly_roots", []), data.get("kind", "research"))
    if args.cmd == "project-rules":
        data = request_file(args.file)
        if type(data) is not dict or "rules_text" not in data or set(data)-{"rules_text", "allowed_actions", "readonly_roots"}:
            raise ValueError("Unknown rules request fields")
        return projects.update_rules(system, args.project, data["rules_text"],
                                     data.get("allowed_actions"), data.get("readonly_roots"))
    if args.cmd == "goal-register":
        data = request_file(args.file)
        if type(data) is not dict or set(data)-{"id", "text", "plan", "purpose"}:
            raise ValueError("Unknown goal request fields")
        return projects.save_goal(system, args.project, data["id"], data["text"], data["plan"], data.get("purpose", "research"))
    if args.cmd == "goal-plan":
        p = projects.get_project(system, args.project)
        context = {"project_id": p["id"], "profile": p["profile"], "rules_sha256": p["rules_sha256"],
            "rules_text": p["rules"]["text"], "allowed_actions": p["rules"]["allowed_actions"],
            "readonly_roots": p["rules"]["readonly_roots"], "roles": p["roles"]}
        return planning.propose(system, context, request_file(args.file), args.id)
    if args.cmd == "goal-adopt":
        planning.uuid_value(args.proposal)
        base = no_links(system.runtime/"projects"/planning.uuid_value(args.project)/"proposals"/args.proposal)
        proposal, package = request_file(base/"proposal.json", 262144), request_file(base/"request.json", 262144)
        p = projects.get_project(system, args.project)
        if (proposal.get("status") != "PLANNED" or proposal.get("id") != args.proposal or proposal["project_id"] != args.project
                or package["project"]["project_id"] != args.project
                or proposal["goal_id"] != package["request"]["goal_id"]
                or proposal["source_sha256"] != manifest(system.root)["sha256"]
                or proposal["binding_sha256"] != digest(canonical(package))
                or package["project"]["rules_sha256"] != p["rules_sha256"]
                or package["machine_sha256"] != digest(canonical(system.machine))):
            raise ValueError("Proposal is stale or not a dispatchable plan")
        planning.uuid_value(proposal["call_id"])
        recorded = system.db.execute("SELECT task,stage,engine,state,result FROM attempts WHERE id=?",
                                     (proposal["call_id"],)).fetchone()
        charge = system.db.execute("SELECT c.purpose,e.engine,e.task,e.stage FROM calls c JOIN call_engines e "
                                   "ON e.call=c.id WHERE c.id=?", (proposal["call_id"],)).fetchone()
        if (recorded is None or tuple(recorded)[:4] != (args.proposal, "review", "claude", "COMPLETED")
                or tuple(charge or ()) != (args.proposal+":review", "claude", args.proposal, "review")
                or json.loads(recorded["result"] or "null") != proposal["evidence"]):
            raise ValueError("Proposal does not match the original completed Claude attempt and ledger")
        raw = read_json(no_links(system.runtime/"tasks"/args.proposal/"attempts"/proposal["call_id"]/"result.json"))
        if raw.get("evidence") != proposal["evidence"]:
            raise ValueError("Planning evidence differs from its retained attempt")
        expanded = planning.expand_proposal(raw["value"], proposal["binding_sha256"], package["request"],
                    package["task_slots"], p["rules"]["allowed_actions"], system.acceptance_for)
        if expanded != proposal["plan"]:
            raise ValueError("Proposal differs from the recorded validated CLI result")
        return projects.save_goal(system, args.project, proposal["goal_id"], package["request"]["prompt"],
                    expanded, "ops-smoke" if p["kind"] == "ops-smoke" else "research",
                    expected_rules_sha=p["rules_sha256"], expected_source_sha=proposal["source_sha256"])
    if args.cmd == "goal-approve":
        return projects.approve_goal(system, args.project, args.goal, args.plan_sha,
                                     authorization_file(args.authorization_file))
    goal = projects.get_goal(system, args.project, args.goal)
    if args.cycle and len(goal["plan"]) != 1:
        raise ValueError("Source acceptance cycle permits its single fixed task only")
    return {"submitted": [system.submit(task["id"], task["action"], task["input"], "codex", args.cycle,
                                       args.project, args.goal) for task in goal["plan"]]}


def scene_catalog(system):
    """Registered tools and skills with their pinned and current bindings (read-only)."""
    from researchops.analysis_context import analysis_context
    tools, skills = scene.registry(system.root)
    try:
        current, problem = scene.current_bindings(system.root), None
    except (OSError, ValueError) as exc:
        current, problem = None, type(exc).__name__
    pinned = scene.pinned_bindings(system.root)
    return {"tools": {k: {f: v[f] for f in ("purpose", "params", "outputs", "bindings", "gpu", "remote")}
                      for k, v in tools["tools"].items()},
            "skills": {k: {f: v[f] for f in ("file", "sha256", "applies_to", "profiles", "tools", "acceptance")}
                       for k, v in skills.items()},
            "scenes": {k: {"path": v["path"], "rooms": v["rooms"]} for k, v in tools["scenes"].items()},
            "external": tools["external"], "bindings_pinned": pinned, "bindings_current": current,
            "native_skills": read_json(system.root/"config/native-skills.json")["skills"],
            "analysis_skills": analysis_context(system.root)["skills"],
            "bindings_ok": current == pinned, "binding_error": problem}


def main():
    if os.name != "nt":
        raise SystemExit("Windows local only")
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    p.add_argument("--runtime", type=Path, default=REPO/".runtime")
    p.add_argument("--expected-hash")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("identity")
    sub.add_parser("pause")
    s = sub.add_parser("resume")
    s.add_argument("--engine", choices=["codex", "claude"])
    sub.add_parser("tools")
    s = sub.add_parser("show")
    s.add_argument("--id", required=True)
    s = sub.add_parser("retry")
    s.add_argument("task_id")
    s = sub.add_parser("submit")
    s.add_argument("--id", required=True)
    s.add_argument("--action", required=True,
                   choices=["analyze_numbers", "inspect_text", "analyze_text", "scene_stair_workflow"])
    s.add_argument("--input-file", required=True, type=Path)
    s.add_argument("--writer", choices=["codex", "claude"], default="codex")
    s.add_argument("--cycle")
    s.add_argument("--project")
    s.add_argument("--goal")
    sub.add_parser("projects")
    s = sub.add_parser("project-show")
    s.add_argument("--project", required=True)
    s = sub.add_parser("project-register")
    s.add_argument("--file", type=Path, required=True)
    s = sub.add_parser("project-rules")
    s.add_argument("--project", required=True)
    s.add_argument("--file", type=Path, required=True)
    s = sub.add_parser("goal-register")
    s.add_argument("--project", required=True)
    s.add_argument("--file", type=Path, required=True)
    s = sub.add_parser("brief-prepare")
    s.add_argument("--project", required=True)
    s.add_argument("--file", type=Path, required=True)
    s = sub.add_parser("goal-plan")
    s.add_argument("--project", required=True)
    s.add_argument("--id", required=True)
    s.add_argument("--file", type=Path, required=True)
    s = sub.add_parser("goal-adopt")
    s.add_argument("--project", required=True)
    s.add_argument("--proposal", required=True)
    s = sub.add_parser("goal-approve")
    s.add_argument("--project", required=True)
    s.add_argument("--goal", required=True)
    s.add_argument("--plan-sha", required=True)
    s.add_argument("--authorization-file", type=Path, required=True)
    s = sub.add_parser("goal-submit")
    s.add_argument("--project", required=True)
    s.add_argument("--goal", required=True)
    s.add_argument("--cycle")
    s = sub.add_parser("research-watch")
    s.add_argument("--force", action="store_true")
    s = sub.add_parser("daily-report")
    s.add_argument("--verify-science", action="store_true", help="Explicitly revalidate retained scientific inputs, outputs, source and owned processes")
    s = sub.add_parser("science-check")
    s.add_argument("--id", required=True, help="Accepted historical CPU stair task UUID")
    s = sub.add_parser("authorize-cycle")
    s.add_argument("--cycle-id", required=True)
    s.add_argument("--task-id", required=True)
    s.add_argument("--authorization-file", required=True, type=Path)
    s.add_argument("--reviewer", required=True, choices=["claude", "codex"])
    s.add_argument("--audits", type=int, default=1, help="Legacy finite cycle: 1 to 3 audits")
    s.add_argument("--continuous", action="store_true", help="Explicit new continuous repair authorization; shared 50 reviews per UTC day")
    s = sub.add_parser("close-cycle")
    s.add_argument("--cycle-id", required=True)
    s.add_argument("--reason-file", required=True, type=Path)
    s = sub.add_parser("resume-audit")
    s.add_argument("--cycle-id", required=True)
    s.add_argument("--reason-file", required=True, type=Path)
    for command in ("tick", "run"):
        s = sub.add_parser(command)
        s.add_argument("--trigger", choices=["manual", "scheduled"], default="manual")
    for name in ("audit", "freeze"):
        s = sub.add_parser(name)
        s.add_argument("--tests", required=True, type=Path)
        s.add_argument("--cycle")
        if name == "audit":
            s.add_argument("--reviewer", choices=["claude", "codex"], default="claude")
    args = p.parse_args()
    root, runtime = no_links(args.root), no_links(args.runtime)
    if root != Path(__file__).resolve().parent:
        raise ValueError("--root must be the actually executing source")
    if runtime != REPO/".runtime":
        raise ValueError("Runtime must stay in the unique authorized repository")
    if args.expected_hash:
        verify_activation(root, runtime, args.expected_hash)
    if args.cmd in ("tick", "run") and args.trigger == "scheduled" and not args.expected_hash:
        raise ValueError("Scheduled runs require an accepted snapshot")
    system = System(root, runtime)
    try:
        if args.cmd == "identity":
            result = verify_repo(system.machine)
        elif args.cmd == "status":
            result = system.report(persist=False)
        elif args.cmd == "tick":
            result = system.tick(args.trigger)
        elif args.cmd == "run":
            result = system.run_ready(args.trigger)
        elif args.cmd == "submit":
            result = {"task_id": system.submit(args.id, args.action, read_json(args.input_file), args.writer,
                                               args.cycle, args.project, args.goal)}
        elif args.cmd in ("projects", "project-show", "project-register", "project-rules", "goal-register", "goal-plan",
                          "goal-adopt", "goal-approve", "goal-submit"):
            result = governance_command(system, args)
        elif args.cmd == "brief-prepare":
            from researchops import briefs
            result = briefs.prepare(system, args.project, request_file(args.file))
        elif args.cmd in ("research-watch", "daily-report"):
            from researchops import operations
            with system.lock():
                result = (operations.refresh_watch(system, force=args.force) if args.cmd == "research-watch"
                          else operations.refresh_daily(system, force=True, verify_science=args.verify_science))
        elif args.cmd == "science-check":
            from researchops import science, evidence
            from researchops.integrity import write_json
            from researchops.planning import uuid_value
            task=uuid_value(args.id)
            with system.lock():
                row=system.db.execute("SELECT spec,state FROM tasks WHERE id=?",(task,)).fetchone()
                if row is None or row["state"]!="ACCEPTED":
                    raise ValueError("An accepted registered stair task is required")
                spec=json.loads(row["spec"])
                if spec.get("id")!=task or spec.get("action")!="scene_stair_workflow":
                    raise ValueError("Historical task identity or action mismatch")
                verified_acceptance(system,row["spec"],{"source":spec["source"]})
                store=evidence.EvidenceStore(system.runtime)
                evidence.accepted_static_reference(store,task)
                result=science.run_static_geometry(system,system.runtime/"tasks"/task)
                if result.get("passed") is True:
                    relative=Path(result["report_path"]).relative_to(system.runtime).as_posix()
                    bundle=store.fingerprint(relative)
                    assessment=science.reconstruct_assessment(store,bundle)
                    if assessment["status"]!="READY" or assessment.get("layer")!="STATIC_GEOMETRY":
                        raise ValueError("Bound static controls did not pass")
                    path=no_links(system.runtime/"science-index.json")
                    index=read_json(path) if path.exists() else {}
                    index[task]=bundle.as_dict()
                    write_json(path,index)
                    result={"status":"STATIC_GEOMETRY_READY","task_id":task,"bundle":bundle.as_dict(),
                            "full_research_readiness":"UNVERIFIED","gpu":False,"model_calls":0}
        elif args.cmd == "close-cycle":
            result = close_cycle(system, args.cycle_id, authorization_file(args.reason_file))
        elif args.cmd == "resume-audit":
            result = resume_source_audit(system, args.cycle_id, authorization_file(args.reason_file))
        elif args.cmd == "authorize-cycle":
            text = authorization_file(args.authorization_file)
            result = authorize_cycle(system, args.cycle_id, args.task_id, text, args.reviewer, args.audits, continuous=args.continuous)
        elif args.cmd == "pause":
            result = system.pause()
        elif args.cmd == "resume":
            result = system.resume_engine(args.engine) if args.engine else system.resume()
        elif args.cmd == "tools":
            result = scene_catalog(system)
        elif args.cmd == "show":
            result = system.show(args.id)
        elif args.cmd == "retry":
            result = system.requeue_paused(args.task_id)
        elif args.cmd == "audit":
            result = independent_review(system, args.tests, args.reviewer, args.cycle)
        else:
            result = freeze(system, args.tests, args.cycle)
        if sys.stdout is not None:
            print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        system.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Do not spill prompt/output/credentials into console or unattended logs.
        if sys.stderr is not None:
            print(type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        raise SystemExit(1)

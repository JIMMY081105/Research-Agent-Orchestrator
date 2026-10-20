"""Manual real dual-CLI negative control; never scheduled or dispatched as a queue action.

This file must live at the authorized repository's tools/verify_live_rework.py.
The operator supplies one new task UUID and explicitly opts into real model calls.
It does not manufacture results, modify task states, resume pauses or replace task IDs.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import uuid

REPOSITORY = Path(r"E:\Github\Building-Generation-Validation")
sys.path.insert(0, str(REPOSITORY))
from researchops import adapters
from researchops.core import Busy, System, verify_repo, utc
from researchops.integrity import canonical, digest, manifest, no_links, read_json, write_json

DRAFT_MARKER = "CONTROLLED_DRAFT_NEGATIVE_CONTROL:"
TEXT = ("CPU-only sample: one standalone U-shaped stair asset measured 2.85 m by 4.54 m. "
        "Room fitting was checked against generated geometry. "
        "Full building placement, wall and door collisions, and humanoid climbability were not evaluated. "
        "This sample does not establish that a full scene is collision-free or robot-traversable.")
QUESTION = ("In the summary itself, report the measured stair footprint and explain which full-scene "
            "collision and humanoid climbability conclusions this evidence does and does not support. "
            "Answer both parts in English, use the literal terms collision and climbability in the summary, "
            "stay within the supplied evidence and give exact supporting quotations.")
DRAFT_INSTRUCTION = (
    "\nMANUAL CONTROLLED NEGATIVE-CONTROL FIXTURE, FIRST EXECUTION ONLY\n"
    "This initial response intentionally tests the independent reviewer's semantic completeness check. "
    "Return a grounded, schema-valid draft, with every required ID/hash/citation correct. "
    "Begin summary with the exact marker CONTROLLED_DRAFT_NEGATIVE_CONTROL: and summarize only the "
    "2.85 m by 4.54 m measurement. Intentionally omit the requested conclusion about limitations. "
    "Do not mention collision, climbability, traversability, support, verification or unevaluated limitations "
    "in this first summary; cite the exact first sentence only. This omission is an intentional test defect. "
    "Do not fabricate any result. Do not add fields. Later attempts use ordinary production instructions.\n")


class FixtureBlocked(Exception):
    pass


class FixtureSystem(System):
    """Use production advancement while refusing to dispatch or recover another task."""
    fixture_task_id = None

    def recover(self):
        other = self.db.execute(
            "SELECT id FROM tasks WHERE id!=? AND state IN "
            "('EXECUTING','REVIEWING','QUEUED','REWORK','AWAITING_REVIEW','WAITING_REVIEW_BUDGET') LIMIT 1",
            (self.fixture_task_id,)).fetchone()
        if other is not None:
            raise FixtureBlocked("OTHER_ACTIONABLE_QUEUE_TASK")
        return super().recover()

    def process(self, row):
        if row["id"] != self.fixture_task_id:
            raise FixtureBlocked("OTHER_TASK_SELECTED")
        return super().process(row)


def task_data(prompt):
    """Decode only task JSON; appended instructions do not alter the recorded data object."""
    if "TASK DATA\n" not in prompt:
        return None
    try:
        return json.JSONDecoder().raw_decode(prompt.split("TASK DATA\n", 1)[1])[0]
    except (ValueError, TypeError):
        return None


def assess(system, task_id, source_before, sent):
    """Judge actual retained production evidence. No model output or state is changed here."""
    failures = []
    def check(condition, code):
        if not condition:
            failures.append(code)
    row = system.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    check(row is not None, "TASK_RECORD_MISSING")
    if row is None:
        return failures, {}
    spec = json.loads(row["spec"])
    folder = system.runtime/"tasks"/task_id
    attempts = [dict(a) for a in system.db.execute(
        "SELECT id,stage,engine,session,state FROM attempts WHERE task=? ORDER BY created,id", (task_id,))]
    check(spec["writer"] == "codex" and spec["reviewer"] == "claude", "WRONG_PRODUCTION_ROLES")
    check(spec["source"] == source_before and manifest(system.root) == source_before, "SOURCE_CHANGED")
    executions = [a for a in attempts if a["stage"] == "execute"]
    reviews = [a for a in attempts if a["stage"] == "review"]
    check(2 <= len(executions) <= 3 and 2 <= len(reviews) <= 3, "MISSING_BOUNDED_REPAIR_CALLS")
    check(1 <= row["reworks"] <= 2, "WRONG_REWORK_COUNT")
    check(row["state"] == "ACCEPTED", "FINAL_STATE_NOT_ACCEPTED")
    records = []
    for attempt in attempts:
        path = folder/"attempts"/attempt["id"]/"result.json"
        result = read_json(path) if path.exists() else None
        evidence = (result or {}).get("evidence", {})
        ledger = system.db.execute(
            "SELECT c.purpose,e.engine,e.task,e.stage FROM calls c LEFT JOIN call_engines e ON e.call=c.id "
            "WHERE c.id=?", (attempt["id"],)).fetchone()
        check(tuple(ledger or ()) == (task_id+":"+attempt["stage"],attempt["engine"],task_id,attempt["stage"]),
              "CALL_LEDGER_MISMATCH:"+attempt["id"])
        check(attempt["state"] == "COMPLETED" and evidence.get("exit_code") == 0,
              "CALL_DID_NOT_COMPLETE:"+attempt["id"])
        check(evidence.get("tools_disabled") is True, "CLI_TOOLS_NOT_DISABLED:"+attempt["id"])
        check(evidence.get("session_id") == attempt["session"], "SESSION_EVIDENCE_MISMATCH:"+attempt["id"])
        records.append({**attempt,"evidence":adapters.safe_evidence(evidence),
                        "result_path":str(path),"sent_prompt_path":str(path.parent/"prompt.txt")})
    first_artifact = None
    first_review = None
    if executions:
        p = folder/"attempts"/executions[0]["id"]/"result.json"
        first_artifact = read_json(p).get("value") if p.exists() else None
    if reviews:
        p = folder/"attempts"/reviews[0]["id"]/"result.json"
        first_review = read_json(p).get("value") if p.exists() else None
    summary = (first_artifact or {}).get("summary", "")
    omitted = not any(word in summary.lower() for word in ("collision","climb","travers","unverified","not evaluated"))
    check(isinstance(summary,str) and summary.startswith(DRAFT_MARKER)
          and "2.85" in summary and "4.54" in summary and omitted,
          "FIRST_DRAFT_DID_NOT_ESTABLISH_CONTROLLED_DEFECT")
    if first_artifact is not None:
        check(system.valid_artifact(spec,first_artifact), "FIRST_DRAFT_SCHEMA_OR_GROUNDING_INVALID")
    if first_artifact is not None and first_review is not None:
        first_binding = system.binding(spec,first_artifact)
        check(system.valid_review(spec,first_binding,first_review), "FIRST_REVIEW_BINDING_INVALID")
        check(first_review.get("verdict") == "REWORK" and bool(first_review.get("issues")),
              "NEGATIVE_CONTROL_INCORRECTLY_PASSED_BY_CLAUDE")
    else:
        failures.append("FIRST_EXECUTION_OR_REVIEW_RESULT_MISSING")
    forwarded = False
    if len(executions) > 1 and first_review is not None:
        second = next((c for c in sent if c["call_id"] == executions[1]["id"]),None)
        feedback = (second or {}).get("review_feedback") or {}
        forwarded = (feedback.get("untrusted_review_data") is True
                     and feedback.get("task_id") == task_id
                     and feedback.get("binding_sha256") == first_review.get("binding_sha256")
                     and feedback.get("issues") == first_review.get("issues"))
    check(forwarded, "BOUND_REVIEW_FEEDBACK_NOT_FORWARDED")
    final_artifact_path = folder/"artifact.json"
    if row["state"] == "ACCEPTED" and final_artifact_path.exists():
        artifact = read_json(final_artifact_path)
        check(system.valid_artifact(spec,artifact), "FINAL_ARTIFACT_INVALID")
        final_summary = artifact.get("summary", "").lower()
        check("2.85" in final_summary and "4.54" in final_summary
              and "collision" in final_summary and "climbability" in final_summary
              and any(term in final_summary for term in ("not ", "unverified", "unsupported", "cannot", "no evidence"))
              and not artifact.get("summary", "").startswith(DRAFT_MARKER),
              "FINAL_SUMMARY_DID_NOT_CORRECT_REQUIRED_CONCLUSION")
        acceptance = read_json(folder/"acceptance.json")
        final_review = read_json(folder/"review.json")["review"]
        bound = system.binding(spec,artifact)
        check(acceptance.get("binding_sha256") == bound
              and final_review == {"task_id":task_id,"binding_sha256":bound,"verdict":"PASS","issues":[]},
              "FINAL_ACCEPTANCE_BINDING_INVALID")
    return failures, {"task_id":task_id,"final_state":row["state"],"reworks":row["reworks"],
        "first_codex_call":next((a for a in records if a["stage"]=="execute"),None),
        "first_claude_call":next((a for a in records if a["stage"]=="review"),None),
        "first_claude_verdict":(first_review or {}).get("verdict"),
        "repair_received_bound_feedback":forwarded,"attempts":records}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live-negative-control",action="store_true",required=True,
                        help="Explicit manual authorization to make real subscription CLI calls")
    parser.add_argument("--task-id",required=True,help="One new canonical UUID, never automatically replaced")
    args=parser.parse_args(argv)
    if os.name != "nt" or Path(__file__).resolve() != REPOSITORY/"tools"/"verify_live_rework.py":
        raise ValueError("Run only the reviewed script installed in the authorized Windows repository")
    if str(uuid.UUID(args.task_id)) != args.task_id:
        raise ValueError("Canonical fixture task UUID required")
    runtime=no_links(REPOSITORY/".runtime")
    folder=no_links(runtime/"continuous-review-20261019"/"live-rework"/args.task_id)
    report_path=folder/"report.json"
    if report_path.exists():
        raise ValueError("Fixture evidence already exists; review it without replaying this task")
    sent=[]
    system=FixtureSystem(REPOSITORY,runtime)
    system.fixture_task_id=args.task_id
    original_invoke=adapters.invoke
    first_injected=False
    report={"fixture":"manual-real-grounded-draft-review-repair","task_id":args.task_id,
            "started_at":utc(),"status":"STARTED","intentional_defect":
            "First Codex summary includes measured footprint but intentionally omits requested collision/climbability conclusion.",
            "limits":{"max_reworks":2,"max_model_calls":6},"report_path":str(report_path)}
    try:
        verify_repo(system.machine)
        if system.db.execute("SELECT 1 FROM tasks WHERE id=?",(args.task_id,)).fetchone():
            raise FixtureBlocked("TASK_ID_ALREADY_EXISTS_NO_REPLAY")
        if system.meta("paused") or any(system.engine_paused(e) for e in ("codex","claude")):
            raise FixtureBlocked("EXISTING_PAUSE_REQUIRES_OPERATOR_HANDLING")
        with system.lock():
            system.recover()  # refuses other actionable tasks before mutating anything
        source_before=manifest(REPOSITORY)
        report["source_sha256"]=source_before["sha256"]
        report["fixture_script_sha256"]=digest(Path(__file__).read_bytes())
        write_json(report_path,report)

        def real_caller(engine,machine,policy,prompt,schema,cwd,on_start,session):
            nonlocal first_injected
            attempt_dir=no_links(Path(schema).parent)
            attempt=system.db.execute("SELECT id,task,stage,engine,session FROM attempts WHERE id=?",
                                      (attempt_dir.name,)).fetchone()
            if (attempt is None or attempt["task"] != args.task_id or attempt["session"] != session
                    or attempt["engine"] != engine
                    or attempt_dir != runtime/"tasks"/args.task_id/"attempts"/attempt["id"]):
                raise FixtureBlocked("ATTEMPT_IDENTITY_MISMATCH")
            prompt_path=attempt_dir/"prompt.txt"
            if prompt_path.read_text(encoding="utf-8") != prompt:
                raise FixtureBlocked("PRODUCTION_PROMPT_EVIDENCE_MISMATCH")
            actual_prompt=prompt
            injected=False
            if attempt["stage"] == "execute" and engine == "codex" and not first_injected:
                first_injected=True;injected=True
                actual_prompt += DRAFT_INSTRUCTION
                first_sentence=TEXT.split("Room fitting",1)[0].rstrip()
                actual_prompt += "Exact controller-verified first-sentence citation data: "+canonical(
                    {"quote":first_sentence,"start":0,"end":len(first_sentence)}).decode()+"\n"
                prompt_path.write_text(actual_prompt,encoding="utf-8",newline="\n")
            data=task_data(actual_prompt) or {}
            sent.append({"call_id":attempt["id"],"requested_session_id":session,"engine":engine,
                         "stage":attempt["stage"],"intentional_draft_injected":injected,
                         "review_feedback":data.get("review_feedback"),
                         "prompt_sha256":digest(actual_prompt.encode("utf-8"))})
            # Every value/verdict/session comes from the actual adapter. Claude's prompt is untouched.
            return original_invoke(engine,machine,policy,actual_prompt,schema,cwd,on_start,session)

        system.caller=real_caller
        system.submit(args.task_id,"analyze_text",{"text":TEXT,"question":QUESTION},"codex")
        run=system.run_ready(trigger="manual",max_stages=6,max_seconds=540)
        failures,details=assess(system,args.task_id,source_before,sent)
        report.update(details,finished_at=utc(),failures=failures,sent=sent,
                      stages_checked=run["stages_checked"],
                      status="PASS" if not failures else "FAILED")
        row=system.db.execute("SELECT state,reason FROM tasks WHERE id=?",(args.task_id,)).fetchone()
        if row and (row["state"].startswith("WAITING_") or row["state"].startswith("PAUSED_")):
            report["status"]="BLOCKED"
            report["blocking_state"]={"state":row["state"],"reason":row["reason"]}
        write_json(report_path,report)
        print(json.dumps({k:report.get(k) for k in ("status","task_id","final_state","reworks",
              "first_claude_verdict","first_codex_call","first_claude_call","failures","report_path")},
              ensure_ascii=False,indent=2))
        return 0 if report["status"]=="PASS" else 2 if report["status"]=="BLOCKED" else 1
    except Exception as error:
        # Do not echo arbitrary CLI output, credentials or model reasoning.
        report.update(status="BLOCKED" if isinstance(error,(FixtureBlocked,Busy)) else "FAILED",
                      finished_at=utc(),error_type=type(error).__name__,sent=sent,
                      error_code=str(error) if isinstance(error,(FixtureBlocked,Busy)) else "UNEXPECTED_FIXTURE_FAILURE")
        write_json(report_path,report)
        print(json.dumps({"status":report["status"],"task_id":args.task_id,
                          "error_type":report["error_type"],"report_path":str(report_path)},indent=2))
        return 2 if isinstance(error,(FixtureBlocked,Busy)) else 1
    finally:
        system.close()


if __name__=="__main__":
    raise SystemExit(main())

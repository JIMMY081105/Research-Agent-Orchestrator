"""Durable allowlisted queue. All mutations serialize under a Windows file lock."""
import contextlib
import datetime as dt
import json
import math
import os
import re
from pathlib import Path
import sqlite3
import subprocess
import time
import uuid
from . import adapters, scene, winproc
from .integrity import canonical, digest, manifest, no_links, read_json, write_json

OWNER = "BGV.Windows.ResearchOps.v1"
TASK_NAME = "BGV-ResearchOps-Observe-v1"
REPO = Path(r"E:\Github\Building-Generation-Validation")
ORIGIN = "https://github.com/JIMMY081105/Building-Generation-Validation.git"
ACTIVE = ("EXECUTING", "REVIEWING")
ENGINES = ("codex", "claude")
# Service-side or local-limit conditions of one engine: wait for that engine, keep the stage.
ENGINE_WAIT = ("AUTH", "QUOTA", "NETWORK", "TIMEOUT", "BUDGET", "REVIEW_BUDGET")
ACTIONS = ("analyze_numbers", "inspect_text", "analyze_text", "scene_stair_workflow")


def is_review_call(purpose, stage=None):
    """Include retained pre-engine-ledger reviews; never refund old attempts."""
    return (stage in ("review", "independent-review")
            or purpose.startswith(("independent-review:", "cycle-review:", "codex-audit-dev:"))
            or re.fullmatch(r"[0-9a-f-]{36}:review", purpose) is not None)


def cycle_allowance_available(record, kind):
    allowed = record["allowed"][kind]
    if allowed is None:
        return kind == "audit" and record.get("continuous") is True
    return type(allowed) is int and record["used"][kind] < allowed


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


class Busy(Exception):
    pass


class Lock:
    def __init__(self, path):
        self.path = no_links(path)

    def __enter__(self):
        import msvcrt
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+b")
        try:
            if os.fstat(self.file.fileno()).st_size == 0:
                self.file.write(b"0")
                self.file.flush()
            self.file.seek(0)
            msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.file.close()
            raise Busy("Another system instance owns the lock")
        return self

    def __exit__(self, *args):
        import msvcrt
        self.file.seek(0)
        msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        self.file.close()


def source_spans(data):
    """Optional literal excerpt boundaries narrow citations, never grant capabilities."""
    if "source_spans" not in data:
        return None
    spans = data["source_spans"]
    if type(spans) is not list or not 1 <= len(spans) <= 8:
        raise ValueError("Expected one to eight source-body spans")
    previous = 0
    for span in spans:
        if (type(span) is not list or len(span) != 2 or any(type(v) is not int for v in span)
                or not previous <= span[0] < span[1] <= len(data["text"])):
            raise ValueError("Invalid or overlapping source-body spans")
        previous = span[1]
    return spans


def expected(action, data):
    if action == "analyze_numbers":
        if not isinstance(data, list) or len(data) > 100 or not all(type(n) is int and abs(n) <= 1000000 for n in data):
            raise ValueError("Expected <=100 bounded integers")
        return {"sum": sum(data), "sorted": sorted(data)}
    if action == "inspect_text":
        if not isinstance(data, str):
            raise ValueError("Expected literal text")
        return {"line_count": len(data.splitlines()), "word_count": len(data.split())}
    if action == "analyze_text":
        if (type(data) is not dict or set(data) not in ({"text", "question"}, {"text", "question", "source_spans"})
                or not all(type(data[k]) is str and data[k].strip() for k in ("text", "question"))
                or len(data["question"]) > 2000):
            raise ValueError("Expected literal text and a bounded research question")
        source_spans(data)
        return {"summary": "answer grounded in supplied text, 10..5000 characters",
                "citations": "1..8 exact quotes with Python character start/end offsets",
                "semantic_review": "independent reviewer must approve grounding and relevance"}
    raise ValueError("Action is not authorized")


def schema_for(value):
    def prop(v):
        if type(v) is int:
            return {"type": "integer"}
        if isinstance(v, list):
            return {"type": "array", "items": {"type": "integer"}}
        return {"type": "string"}
    return {"type": "object", "properties": {k: prop(v) for k, v in value.items()},
            "required": list(value), "additionalProperties": False}


REVIEW_SCHEMA = {"type": "object", "properties": {
    "task_id": {"type": "string"}, "binding_sha256": {"type": "string"},
    "verdict": {"type": "string", "enum": ["PASS", "REWORK"]},
    "issues": {"type": "array", "items": {"type": "string"}}},
    "required": ["task_id", "binding_sha256", "verdict", "issues"], "additionalProperties": False}


class System:
    def __init__(self, root, runtime, caller=None):
        self.root, self.runtime = no_links(root), no_links(runtime)
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.policy = read_json(self.root/"config/policy.json")
        limits = self.policy["engine_daily_limits"]
        # No fixed global cap: each engine may have an optional local daily cap (null = none);
        # the service's own limits surface as QUOTA and pause only that engine.
        if (set(limits) != set(ENGINES) or "daily_model_calls" in self.policy
                or type(self.policy.get("daily_review_limit")) is not int
                or not 1 <= self.policy["daily_review_limit"] <= 50
                or any(v is not None and (type(v) is not int or v < 1) for v in limits.values())
                or self.policy["max_reworks"] > 2 or not 1 <= self.policy["max_engine_resumes"] <= 5
                or not 1 <= self.policy["timeout_seconds"] <= 600
                or type(self.policy["tool_timeout_seconds"]) is not int or not 1 <= self.policy["tool_timeout_seconds"] <= 1800
                or type(self.policy["tool_memory_mb"]) is not int or not 256 <= self.policy["tool_memory_mb"] <= 16384
                or self.policy["research_write"] or self.policy["gpu"] or self.policy["publish"]
                or set(self.policy["actions"]) - set(ACTIONS)):
            raise ValueError("Policy exceeds deployment authorization")
        self.machine = read_json(self.runtime/"machine.json") if (self.runtime/"machine.json").exists() else {}
        self.caller = caller or adapters.invoke
        self.db = sqlite3.connect(no_links(self.runtime/"queue.sqlite3"), timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
          PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;
          CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, spec TEXT NOT NULL,
            state TEXT NOT NULL, reworks INTEGER NOT NULL DEFAULT 0, reason TEXT,
            created TEXT NOT NULL, updated TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY, task TEXT NOT NULL,
            stage TEXT NOT NULL, engine TEXT NOT NULL, session TEXT NOT NULL, pid INTEGER,
            birth TEXT, state TEXT NOT NULL, created TEXT NOT NULL, result TEXT);
          CREATE TABLE IF NOT EXISTS calls(id TEXT PRIMARY KEY, day TEXT NOT NULL,
            purpose TEXT NOT NULL, created TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,
            time TEXT NOT NULL, task TEXT, event TEXT NOT NULL, detail TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS review_cycles(id TEXT PRIMARY KEY, task TEXT UNIQUE NOT NULL,
            record TEXT NOT NULL, state TEXT NOT NULL, created TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS cycle_calls(call TEXT PRIMARY KEY, cycle TEXT NOT NULL,
            kind TEXT NOT NULL, created TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS call_engines(call TEXT PRIMARY KEY, engine TEXT NOT NULL,
            task TEXT, stage TEXT);
          CREATE TABLE IF NOT EXISTS task_waits(task TEXT PRIMARY KEY, stage TEXT NOT NULL,
            engine TEXT NOT NULL, prior TEXT NOT NULL, kind TEXT NOT NULL, launched INTEGER NOT NULL,
            resumes INTEGER NOT NULL, updated TEXT NOT NULL);
        """)
        self.db.commit()

    def close(self):
        self.db.close()

    def lock(self):
        return Lock(self.runtime/"controller.lock")

    # commit=False lets a caller commit a change and its event record as one transaction.
    def event(self, event, task=None, detail=None, commit=True):
        self.db.execute("INSERT INTO events(time,task,event,detail) VALUES(?,?,?,?)",
                        (utc(), task, event, json.dumps(detail or {}, ensure_ascii=False)))
        if commit:
            self.db.commit()

    def meta(self, key, default=None):
        r = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(r[0]) if r else default

    def set_meta(self, key, value, commit=True):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, json.dumps(value)))
        if commit:
            self.db.commit()

    def state(self, task, state, reason=None, commit=True):
        self.db.execute("UPDATE tasks SET state=?,reason=?,updated=? WHERE id=?", (state, reason, utc(), task))
        self.event(state, task, {"reason": reason}, commit)

    def reserve(self, purpose, within=None, engine=None, task=None, stage=None):
        """Atomically record one model call in the ledger before it is launched.

        Every call is recorded (engine, task, stage, time). An engine is refused only if the
        policy sets a local daily cap for it. `within(call_id)` runs in the same write
        transaction (round/cycle charges), so a refused charge also releases the entry.
        """
        day = utc()[:10]
        if engine not in ENGINES:
            raise ValueError("Every model call must name its engine")
        if not self.db.in_transaction:
            self.db.execute("BEGIN IMMEDIATE")
        try:
            if is_review_call(purpose, stage) and self.reviews_today(day) >= self.policy["daily_review_limit"]:
                raise adapters.CallError("REVIEW_BUDGET")
            limit = self.policy["engine_daily_limits"][engine]
            if limit is not None and self.db.execute(
                    "SELECT count(*) FROM calls JOIN call_engines ON call_engines.call=calls.id "
                    "WHERE calls.day=? AND call_engines.engine=?", (day, engine)).fetchone()[0] >= limit:
                raise adapters.CallError("BUDGET")
            call_id = str(uuid.uuid4())
            self.db.execute("INSERT INTO calls VALUES(?,?,?,?)", (call_id, day, purpose, utc()))
            self.db.execute("INSERT INTO call_engines VALUES(?,?,?,?)", (call_id, engine, task, stage))
            if within:
                within(call_id)
            self.db.commit()
            return call_id
        except BaseException:
            self.db.rollback()
            raise

    def reviews_today(self, day=None):
        rows = self.db.execute(
            "SELECT c.purpose,e.stage FROM calls c LEFT JOIN call_engines e ON e.call=c.id WHERE c.day=?",
            (day or utc()[:10],))
        return sum(is_review_call(row[0], row[1]) for row in rows)

    def engine_paused(self, engine):
        return self.meta("engine_pause:" + engine)

    def pause_engine(self, engine, reason, task=None, detail=None):
        """Pause one engine (with its event) without stopping work for the other engine."""
        self.set_meta("engine_pause:" + engine, {"reason": reason, "task": task, "time": utc()}, commit=False)
        self.event("ENGINE_PAUSED", task, {"engine": engine, "reason": reason, **(detail or {})})

    def pause_for(self, reason, event, task=None, detail=None):
        """Global pause and its event record in one transaction."""
        self.set_meta("paused", {"reason": reason, **({"task": task} if task else {})}, commit=False)
        self.event(event, task, {"reason": reason, **(detail or {})})

    # --- Explicitly authorized, bounded review cycles (see deployment.authorize_cycle) ---
    def cycle(self, cycle_id):
        row = self.db.execute("SELECT record,state FROM review_cycles WHERE id=?", (cycle_id,)).fetchone()
        return (json.loads(row[0]), row[1]) if row else (None, None)

    def save_cycle(self, cycle_id, record, state, event, detail=None, commit=True):
        self.db.execute("UPDATE review_cycles SET record=?,state=? WHERE id=?",
                        (canonical(record).decode(), state, cycle_id))
        self.event(event, None, {"cycle": cycle_id, "state": state, **(detail or {})}, commit)

    def charge_cycle(self, cycle_id, kind, call_id, source=None):
        """Inside reserve(): take one of the cycle's fixed allowances or refuse with CYCLE_LIMIT."""
        record, state = self.cycle(cycle_id)
        wanted = {"audit": "OPEN", "execute": "APPROVED", "review": "APPROVED"}[kind]
        if (record is None or state != wanted or not cycle_allowance_available(record, kind)
                or (kind != "audit" and source != record["binding"]["source"])):
            raise adapters.CallError("CYCLE_LIMIT")
        record["used"][kind] += 1
        record["calls"].append({"call": call_id, "kind": kind})
        self.db.execute("INSERT INTO cycle_calls VALUES(?,?,?,?)", (call_id, cycle_id, kind, utc()))
        self.save_cycle(cycle_id, record, "AUDITING" if kind == "audit" else state,
                        "CYCLE_CALL_CHARGED", {"kind": kind, "call": call_id}, commit=False)
        return record

    def submit(self, task_id, action, data, writer="codex", cycle=None, project=None, goal=None):
        uuid.UUID(task_id)
        if str(uuid.UUID(task_id)) != task_id:
            raise ValueError("Canonical task UUID required")
        if action not in self.policy["actions"] or writer not in ("codex", "claude"):
            raise ValueError("Unauthorized action or writer")
        acceptance = self.acceptance_for(action, data)
        if len(canonical(data)) > self.policy["max_input_bytes"]:
            raise ValueError("Input too large")
        spec = {"id": task_id, "action": action, "input": data, "writer": writer,
                "reviewer": "claude" if writer == "codex" else "codex",
                "allowed_actions": [action], "acceptance": acceptance,
                "input_sha256": digest(canonical(data)), "source": manifest(self.root),
                "workdir": str(self.runtime/"tasks"/task_id/"work"),
                "resources": {k: self.policy[k] for k in ("timeout_seconds", "memory_mb", "max_reworks")}}
        if cycle is not None:
            spec["cycle"] = cycle
        if project is not None or goal is not None:
            if project is None or goal is None:
                raise ValueError("Project and approved goal must be supplied together")
            from . import projects
            spec["project_binding"] = projects.binding_for_submission(self, project, goal, action, writer)
            spec["workdir"] = str(no_links(Path(spec["project_binding"]["output_root"])/task_id))
            if not projects.binding_current(self, spec):
                raise ValueError("Task/input is outside the current approved project plan")
        text = canonical(spec).decode()
        with self.lock():
            if "project_binding" in spec and not projects.binding_current(self, spec):
                raise ValueError("Project authorization changed before submission")
            prior = self.db.execute("SELECT spec FROM tasks WHERE id=?", (task_id,)).fetchone()
            if prior:
                if prior[0] != text:
                    raise ValueError("Task ID exists with different input or source")
                return task_id
            if cycle is not None:
                # The task_id registered by authorize-cycle is the one acceptance task, which must
                # run at exactly the audited source. (Identical resubmission returned above.)
                record, state = self.cycle(cycle)
                if (state != "APPROVED" or record.get("acceptance_task") or writer != record["writer"]
                        or task_id != record["task_id"]
                        or spec["source"] != record["binding"]["source"]):
                    raise ValueError("Cycle does not admit this acceptance task")
                record["acceptance_task"] = task_id
                self.save_cycle(cycle, record, state, "CYCLE_TASK_BOUND", {"task": task_id}, commit=False)
            folder = self.runtime/"tasks"/task_id
            no_links(Path(spec["workdir"])).mkdir(parents=True, exist_ok=True)
            write_json(folder/"spec.json", spec)
            self.db.execute("INSERT INTO tasks(id,spec,state,created,updated) VALUES(?,?,?,?,?)",
                            (task_id, text, "QUEUED", utc(), utc()))
            self.event("SUBMITTED", task_id, {"action": action, **({"cycle": cycle} if cycle else {})})
        return task_id

    def acceptance_for(self, action, data):
        """Acceptance description; registered scene workflows are validated against the registry."""
        if action == "analyze_text":
            from .analysis_context import analysis_context
            analysis_context(self.root)  # refuse a changed registered skill before queue admission
        return scene.validate_input(self.root, data) if action == scene.ACTION else expected(action, data)

    def binding(self, spec, artifact):
        return digest(canonical({"spec": spec, "artifact": artifact}))

    def project_context(self, spec):
        if "project_binding" not in spec:
            return None
        from . import projects
        return projects.project_context(self, spec)

    def artifact_expected(self, spec):
        return {"task_id": spec["id"], "input_sha256": spec["input_sha256"],
                "source_sha256": spec["source"]["sha256"], **expected(spec["action"], spec["input"])}

    def artifact_schema(self, spec):
        if spec["action"] != "analyze_text":
            return schema_for(self.artifact_expected(spec))
        props = {k: {"type": "string"} for k in ("task_id", "input_sha256", "source_sha256", "summary")}
        props["citations"] = {"type": "array", "items": {"type": "object", "properties": {
            "quote": {"type": "string"}, "start": {"type": "integer"}, "end": {"type": "integer"}},
            "required": ["quote", "start", "end"], "additionalProperties": False}}
        return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}

    def valid_artifact(self, spec, artifact):
        if spec["action"] == scene.ACTION:
            return scene.valid_artifact(self, spec, artifact)
        if spec["action"] == "analyze_text":
            if (type(artifact) is not dict or set(artifact) != {"task_id", "input_sha256", "source_sha256", "summary", "citations"}
                    or artifact["task_id"] != spec["id"] or artifact["input_sha256"] != spec["input_sha256"]
                    or artifact["source_sha256"] != spec["source"]["sha256"]
                    or type(artifact["summary"]) is not str or not 10 <= len(artifact["summary"]) <= 5000
                    or type(artifact["citations"]) is not list or not 1 <= len(artifact["citations"]) <= 8
                    or len(canonical(artifact)) > self.policy["max_artifact_bytes"]):
                return False
            text = spec["input"]["text"]
            try:
                spans = source_spans(spec["input"])
            except (ValueError, KeyError, TypeError):
                return False
            for cite in artifact["citations"]:
                if (type(cite) is not dict or set(cite) != {"quote", "start", "end"}
                        or type(cite["start"]) is not int or type(cite["end"]) is not int
                        or not 0 <= cite["start"] < cite["end"] <= len(text)
                        or type(cite["quote"]) is not str or text[cite["start"]:cite["end"]] != cite["quote"]):
                    return False
                if spans is not None and not any(start <= cite["start"] < cite["end"] <= end for start, end in spans):
                    return False
            return True
        return (type(artifact) is dict and canonical(artifact) == canonical(self.artifact_expected(spec))
                and len(canonical(artifact)) <= self.policy["max_artifact_bytes"])

    def valid_review(self, spec, binding, review):
        """Task review schema: exact keys, bound IDs, bounded issue text."""
        return (type(review) is dict and set(review) == {"task_id", "binding_sha256", "verdict", "issues"}
                and review["task_id"] == spec["id"] and review["binding_sha256"] == binding
                and review["verdict"] in ("PASS", "REWORK") and type(review["issues"]) is list
                and len(review["issues"]) <= 20 and all(type(i) is str and len(i) <= 2000 for i in review["issues"])
                and (review["verdict"] == "REWORK") == bool(review["issues"])
                and len(canonical(review)) <= self.policy["max_artifact_bytes"])

    def current(self, spec):
        folder = self.runtime/"tasks"/spec["id"]
        current = (manifest(self.root) == spec["source"]
                and read_json(folder/"spec.json") == spec
                and digest(canonical(spec["input"])) == spec["input_sha256"])
        if current and "project_binding" in spec:
            from . import projects
            current = (projects.binding_current(self, spec)
                       and projects.dependency_status(self, spec) == "READY")
        return current

    def recover(self):
        # Called after acquiring singleton lock and before any new dispatch.
        scene.recover_tool_profiles(self)
        for row in self.db.execute("SELECT * FROM tasks WHERE state IN ('EXECUTING','REVIEWING')").fetchall():
            a = self.db.execute("SELECT * FROM attempts WHERE task=? ORDER BY created DESC LIMIT 1", (row["id"],)).fetchone()
            live = winproc.identity(a["pid"]) if a and a["pid"] else "UNKNOWN"
            if a and not a["pid"]:
                # Died before the child's PID was recorded; the child, if created, was in the
                # controller's kill-on-close job and ended with it.
                reason = "START_INTERRUPTED_NO_REPLAY"
            else:
                reason = "ORPHAN_ALIVE" if a and a["birth"] and live == a["birth"] else (
                    "ORPHAN_UNKNOWN" if live == "UNKNOWN" else "AMBIGUOUS_COMPLETION_NO_REPLAY")
            self.state(row["id"], "NEEDS_ATTENTION", reason, commit=False)
            self.pause_for(reason, "RECOVERY_PAUSE", row["id"])

    def retry(self, spec, reason, commit=True):
        row = self.db.execute("SELECT reworks FROM tasks WHERE id=?", (spec["id"],)).fetchone()
        if row[0] >= self.policy["max_reworks"]:
            self.state(spec["id"], "NEEDS_ATTENTION", "REWORK_LIMIT:"+reason, commit)
        else:
            self.db.execute("UPDATE tasks SET reworks=reworks+1 WHERE id=?", (spec["id"],))
            self.state(spec["id"], "REWORK", reason, commit)

    def review_feedback(self, spec):
        """Only the exact prior bound review is repair data; it grants no tools or commands."""
        folder = self.runtime/"tasks"/spec["id"]
        row = self.db.execute("SELECT reworks FROM tasks WHERE id=?", (spec["id"],)).fetchone()
        if not row or row[0] <= 0:
            return None
        try:
            artifact = read_json(folder/"artifact.json")
            stored = read_json(folder/"review.json")
            review, call_id = stored["review"], stored["call_id"]
            if type(call_id) is not str or str(uuid.UUID(call_id)) != call_id:
                return None
            result = read_json(no_links(folder/"attempts"/call_id/"result.json"))
            attempt = self.db.execute("SELECT task,stage,engine,state,result FROM attempts WHERE id=?", (call_id,)).fetchone()
            binding = self.binding(spec, artifact)
            if (not self.current(spec) or not self.valid_artifact(spec, artifact)
                    or not self.valid_review(spec, binding, review) or review["verdict"] != "REWORK"
                    or result.get("value") != review or result.get("evidence") != stored["evidence"]
                    or tuple(attempt or ())[:4] != (spec["id"], "review", spec["reviewer"], "COMPLETED")
                    or json.loads(attempt["result"] or "null") != stored["evidence"]):
                return None
            return {"untrusted_review_data": True, "task_id": spec["id"], "reworks": row[0],
                    "binding_sha256": binding, "previous_artifact_sha256": digest(canonical(artifact)),
                    "issues": review["issues"]}
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def remaining_timeout(self, configured):
        """The scheduler's bounded drain shares one deadline across tools and CLI stages."""
        deadline = getattr(self, "_run_deadline", None)
        if deadline is None:
            return configured
        remaining = math.floor(deadline-time.monotonic())
        if remaining < 1:
            error = adapters.CallError("TIMEOUT")
            error.launched = False
            raise error
        return min(configured, remaining)

    def call(self, spec, stage, engine, prompt, schema, validate):
        """Run one budgeted CLI call. Only a response that passes `validate` is persisted."""
        timeout = self.remaining_timeout(self.policy["timeout_seconds"])
        within = None
        if spec.get("cycle"):
            within = lambda call_id: self.charge_cycle(spec["cycle"], stage, call_id, spec["source"])
        try:
            call_id = self.reserve(spec["id"]+":"+stage, within, engine, spec["id"], stage)
        except adapters.CallError as e:
            e.launched = False  # refused before any process existed
            raise
        session = str(uuid.uuid4())
        launched = []
        folder = self.runtime/"tasks"/spec["id"]/"attempts"/call_id
        folder.mkdir(parents=True)
        (folder/"prompt.txt").write_text(prompt, encoding="utf-8")
        write_json(folder/"schema.json", schema)
        self.db.execute("INSERT INTO attempts(id,task,stage,engine,session,state,created) VALUES(?,?,?,?,?,?,?)",
                        (call_id, spec["id"], stage, engine, session, "STARTING", utc()))
        self.db.commit()

        def on_start(pid, birth):
            if not birth or birth == "UNKNOWN":
                raise RuntimeError("Cannot establish child identity")
            self.db.execute("UPDATE attempts SET pid=?,birth=?,state='RUNNING' WHERE id=?", (pid, birth, call_id))
            self.db.commit()
            launched.append(pid)
            write_json(folder/"process.json", {"pid": pid, "birth": birth, "owner": OWNER,
                                               "session_id": session, "stage": stage})
        try:
            value, evidence = self.caller(engine, self.machine, {**self.policy, "timeout_seconds": timeout}, prompt,
                                          folder/"schema.json", Path(spec["workdir"]), on_start, session)
            evidence = adapters.safe_evidence(evidence)
            if not validate(value):
                # Rejected output is dropped here: no value, text or field names reach disk.
                write_json(folder/"failure.json", {"kind": "REJECTED_OUTPUT", "evidence": evidence})
                self.db.execute("UPDATE attempts SET state='REJECTED',result=? WHERE id=?",
                                ("REJECTED_OUTPUT", call_id))
                self.db.commit()
                return None, evidence, call_id
            write_json(folder/"result.json", {"value": value, "evidence": evidence})
            self.db.execute("UPDATE attempts SET state='COMPLETED',session=?,result=? WHERE id=?",
                            (evidence.get("session_id", session), json.dumps(evidence), call_id))
            self.db.commit()
            return value, evidence, call_id
        except adapters.CallError as e:
            e.launched = bool(launched)
            write_json(folder/"failure.json", {"kind": e.kind, "evidence": e.evidence, "launched": e.launched})
            self.db.execute("UPDATE attempts SET state='FAILED',result=? WHERE id=?", (e.kind, call_id))
            self.db.commit()
            raise

    def process(self, row):
        spec = json.loads(row["spec"])
        if spec.get("id") != row["id"]:
            self.state(row["id"], "NEEDS_ATTENTION", "QUEUE_TASK_ID_MISMATCH")
            return
        folder = self.runtime/"tasks"/spec["id"]
        if not self.current(spec):
            self.state(spec["id"], "NEEDS_ATTENTION", "STALE_SOURCE_OR_INPUT")
            return
        try:
            if row["state"] in ("QUEUED", "REWORK") and spec["action"] == scene.ACTION:
                self.state(spec["id"], "EXECUTING")
                artifact, meta, call_id, passed = scene.execute_stage(self, spec)
                if artifact is None or meta.get("exit_code") != 0:
                    self.retry(spec, "SELECTION_REJECTED")
                    return
                if not passed:
                    write_json(Path(spec["workdir"])/("failed-report-%d.json" % row["reworks"]), artifact)
                    self.retry(spec, "SCENE_CHECKS_FAILED")
                    return
                if not self.current(spec) or not self.valid_artifact(spec, artifact):
                    self.state(spec["id"], "NEEDS_ATTENTION", "STALE_AFTER_EXECUTION")
                    return
                write_json(folder/"artifact.json", artifact)
                write_json(folder/"writer.json", {"call_id": call_id, "engine": spec["writer"], "evidence": meta})
                self.state(spec["id"], "AWAITING_REVIEW")
                return
            if row["state"] in ("QUEUED", "REWORK"):
                self.state(spec["id"], "EXECUTING")
                prompt = (self.root/"prompts/execute.txt").read_text(encoding="utf-8")
                if spec["action"] == "analyze_text":
                    from .analysis_context import analysis_context
                    prompt += analysis_context(self.root)["text"]
                citation = None
                if spec["action"] == "analyze_text":
                    start, end = (source_spans(spec["input"]) or [[0, len(spec["input"]["text"])]])[0]
                    citation = {"quote": spec["input"]["text"][start:end], "start": start, "end": end}
                prompt += "\nTASK DATA\n" + canonical({"task_id": spec["id"], "action": spec["action"],
                    "input": spec["input"], "input_sha256": spec["input_sha256"],
                    "source_sha256": spec["source"]["sha256"],
                    "project_context": self.project_context(spec),
                    "review_feedback": self.review_feedback(spec),
                    "citation_example": citation}).decode()
                artifact, meta, call_id = self.call(spec, "execute", spec["writer"], prompt,
                                                   self.artifact_schema(spec),
                                                   lambda value: self.valid_artifact(spec, value))
                if artifact is None or meta.get("exit_code") != 0:
                    self.retry(spec, "DETERMINISTIC_ARTIFACT_REJECTED")
                    return
                if not self.current(spec):
                    self.state(spec["id"], "NEEDS_ATTENTION", "STALE_AFTER_EXECUTION")
                    return
                write_json(folder/"artifact.json", artifact)
                write_json(folder/"writer.json", {"call_id": call_id, "engine": spec["writer"], "evidence": meta})
                self.state(spec["id"], "AWAITING_REVIEW")
                return
            artifact = read_json(folder/"artifact.json")
            if not self.valid_artifact(spec, artifact):
                self.retry(spec, "ARTIFACT_CHANGED")
                return
            binding = self.binding(spec, artifact)
            self.state(spec["id"], "REVIEWING")
            prompt = (self.root/"prompts/review.txt").read_text(encoding="utf-8")
            if spec["action"] == "analyze_text":
                from .analysis_context import analysis_context
                prompt += analysis_context(self.root)["text"]
            if spec["action"] == scene.ACTION:
                prompt += scene.skill_context(self.root, spec["input"]["skill"])
            prompt += "\n"+canonical({"spec": spec, "artifact": artifact, "binding_sha256": binding,
                "acceptance": spec["acceptance"], "project_context": self.project_context(spec),
                "additional_checks": ("scene_stair_workflow: the rationale must be supported by the candidate "
                    "numbers, the chosen template must fit, every deterministic check must be true and nothing in "
                    "not_verified may be claimed" if spec["action"] == scene.ACTION else
                    "exact keys, IDs and hashes; exit 0; analyze_text grounding and relevance")}).decode()
            review, meta, call_id = self.call(spec, "review", spec["reviewer"], prompt, REVIEW_SCHEMA,
                                              lambda value: self.valid_review(spec, binding, value))
            if review is None:
                self.retry(spec, "REVIEW_REJECTED")
                return
            write_json(folder/"review.json", {"review": review, "evidence": meta, "call_id": call_id})
            if (not self.current(spec) or read_json(folder/"artifact.json") != artifact
                    or not self.valid_artifact(spec, artifact)):  # external inputs and outputs re-checked now
                self.state(spec["id"], "NEEDS_ATTENTION", "STALE_REVIEW")
                return
            wanted = {"task_id": spec["id"], "binding_sha256": binding, "verdict": "PASS", "issues": []}
            if review != wanted or meta.get("exit_code") != 0:
                self.retry(spec, "REVIEW_REJECTED")
                return
            write_json(folder/"acceptance.json", {"accepted_at": utc(), "binding_sha256": binding,
                "source_sha256": spec["source"]["sha256"], "artifact_sha256": digest(canonical(artifact)),
                "review_call": call_id, "checks": ["exit_status", "exact_schema", "deterministic_values",
                    "artifact_content", "independent_reviewer", "current_source_and_input"]})
            self.state(spec["id"], "ACCEPTED")
        except adapters.CallError as e:
            if e.kind in ENGINE_WAIT:
                self.wait_for_engine(spec, row["state"], e)
                return
            self.state(spec["id"], "PAUSED_"+e.kind, e.kind, commit=False)
            self.pause_for(e.kind, "CALL_FAILED_PAUSE", spec["id"])
        except scene.NoFit:
            self.state(spec["id"], "NEEDS_ATTENTION", "NO_FITTING_TEMPLATE")
        except Exception as e:
            # No replay after unknown process/IO failure. Do not store arbitrary exception text.
            self.db.rollback()
            self.state(spec["id"], "NEEDS_ATTENTION", type(e).__name__, commit=False)
            self.pause_for("INTERNAL_ERROR", "INTERNAL_ERROR_PAUSE", spec["id"])

    def wait_for_engine(self, spec, prior, error):
        """Park the task at its current stage until that engine is resumed.

        The artifact of a completed execution is kept; nothing is re-run because of a wait.
        State, wait record, engine pause and event commit together.
        """
        stage = "review" if prior == "AWAITING_REVIEW" else "execute"
        engine = spec["reviewer"] if stage == "review" else spec["writer"]
        old = self.db.execute("SELECT resumes FROM task_waits WHERE task=?", (spec["id"],)).fetchone()
        launched = bool(getattr(error, "launched", False))
        self.db.execute("INSERT OR REPLACE INTO task_waits VALUES(?,?,?,?,?,?,?,?)",
                        (spec["id"], stage, engine, prior, error.kind, int(launched), old[0] if old else 0, utc()))
        if error.kind == "REVIEW_BUDGET":
            self.state(spec["id"], "WAITING_REVIEW_BUDGET", error.kind, commit=False)
            self.event("REVIEW_BUDGET_WAIT", spec["id"], {"stage": stage, "engine": engine, "launched": False})
            return  # a shared review cap does not pause this engine's independent executions
        self.state(spec["id"], "WAITING_" + engine.upper(), error.kind, commit=False)
        self.pause_engine(engine, error.kind, spec["id"], {"stage": stage, "launched": launched})

    def resume_engine(self, engine):
        """Return tasks waiting for one engine to their stage. The user pause is never touched."""
        if engine not in ENGINES:
            raise ValueError("Unknown engine")
        with self.lock():
            self.recover()
            self.observe()
            outcome = {}
            for row in self.db.execute("SELECT t.id,t.spec,w.stage,w.prior,w.resumes FROM tasks t JOIN task_waits w "
                                       "ON w.task=t.id WHERE t.state=? ORDER BY t.created",
                                       ("WAITING_" + engine.upper(),)).fetchall():
                task, spec = row["id"], json.loads(row["spec"])
                attempt = self.db.execute("SELECT pid,birth FROM attempts WHERE task=? ORDER BY created DESC LIMIT 1",
                                          (task,)).fetchone()
                if attempt and attempt["pid"] and winproc.identity(attempt["pid"]) in ("UNKNOWN", attempt["birth"]):
                    outcome[task] = "ORIGINAL_PROCESS_NOT_CONFIRMED_GONE"  # stays waiting
                    continue
                if row["resumes"] >= self.policy["max_engine_resumes"]:
                    self.state(task, "NEEDS_ATTENTION", "ENGINE_RESUME_LIMIT", commit=False)
                elif not self.current(spec) or (row["stage"] == "review" and not self.valid_artifact(
                        spec, read_json(self.runtime/"tasks"/task/"artifact.json"))):
                    self.state(task, "NEEDS_ATTENTION", "STALE_WHILE_WAITING", commit=False)
                else:
                    self.db.execute("UPDATE task_waits SET resumes=resumes+1,updated=? WHERE task=?", (utc(), task))
                    self.state(task, row["prior"], "RESUMED_" + row["stage"].upper(), commit=False)
                outcome[task] = self.db.execute("SELECT state FROM tasks WHERE id=?", (task,)).fetchone()[0]
                self.db.commit()
            self.set_meta("engine_pause:" + engine, None, commit=False)
            self.event("ENGINE_RESUMED", None, {"engine": engine, "tasks": outcome})
            return {**self.report(), "resumed": outcome}

    def observe(self):
        # Check local identities first. Optional fixed read-only SSH probe never dispatches.
        registry_path = self.runtime/"legacy-registry.json"
        registry = read_json(registry_path) if registry_path.exists() else {"entries": [], "unknown": True}
        observation = {"entries": []}
        for item in registry.get("entries", [])[:100]:
            entry = {"id": item["id"], "status": "UNKNOWN"}
            if item.get("pid"):
                birth = winproc.identity(item["pid"])
                entry["status"] = "RUNNING" if birth and birth == item.get("birth") else (
                    "UNKNOWN" if birth == "UNKNOWN" else "NO_MATCHING_PROCESS")
            observation["entries"].append(entry)
        sha = digest(canonical(observation))
        changed = sha != self.meta("observation_sha")
        if changed:
            self.set_meta("observation_sha", sha)
            self.event("OBSERVATION_CHANGED", detail=observation)
        write_json(self.runtime/"observation.json", {"time": utc(), "changed": changed,
                   "sha256": sha, "observation": observation, "model_calls": 0,
                   "remote_progress": "See separately registered research-watch evidence"})
        from . import operations
        deadline = getattr(self, "_run_deadline", None)
        if deadline is None or deadline-time.monotonic() >= 35:
            remote = operations.refresh_watch(self)
            changed = changed or remote.get("changed", False)
        return changed

    def resume_daily_review_waits(self):
        """An already authorized UTC rollover resumes only a refused review stage, no refunds."""
        if self.reviews_today() >= self.policy["daily_review_limit"]:
            return
        rows = self.db.execute(
            "SELECT t.id,t.spec,w.prior,w.updated FROM tasks t JOIN task_waits w ON w.task=t.id "
            "WHERE t.state='WAITING_REVIEW_BUDGET' AND w.kind='REVIEW_BUDGET'").fetchall()
        for row in rows:
            if row["updated"][:10] == utc()[:10]:
                continue
            spec = json.loads(row["spec"])
            attempt = self.db.execute("SELECT pid,birth FROM attempts WHERE task=? ORDER BY created DESC LIMIT 1",
                                      (row["id"],)).fetchone()
            if attempt and attempt["pid"] and winproc.identity(attempt["pid"]) in ("UNKNOWN", attempt["birth"]):
                continue
            artifact_path = self.runtime/"tasks"/row["id"]/"artifact.json"
            if not self.current(spec) or not artifact_path.exists() or not self.valid_artifact(spec, read_json(artifact_path)):
                self.state(row["id"], "NEEDS_ATTENTION", "STALE_WHILE_WAITING")
                continue
            self.state(row["id"], row["prior"], "REVIEW_BUDGET_NEW_UTC_DAY", commit=False)
            self.event("REVIEW_BUDGET_RESUMED", row["id"], {"previous_wait_date": row["updated"][:10]})

    def run_ready(self, trigger="manual", max_stages=6, max_seconds=480):
        """Advance a bounded amount of ready work; no task/progress means no model polling."""
        if type(max_stages) is not int or not 1 <= max_stages <= 6:
            raise ValueError("Expected 1..6 stages")
        if type(max_seconds) is not int or not 1 <= max_seconds <= 540:
            raise ValueError("Expected 1..540 seconds between-stage budget")
        started, receipts = time.monotonic(), []
        prior_deadline = getattr(self, "_run_deadline", None)
        self._run_deadline = min(prior_deadline or float("inf"), started+max_seconds)
        try:
            for _ in range(max_stages):
                if time.monotonic() >= self._run_deadline:
                    break
                before = [tuple(r) for r in self.db.execute("SELECT id,state,reworks,updated FROM tasks ORDER BY id")]
                receipt = self.tick(trigger)
                receipts.append(receipt)
                after = [tuple(r) for r in self.db.execute("SELECT id,state,reworks,updated FROM tasks ORDER BY id")]
                if receipt.get("skipped") or before == after or self.meta("paused"):
                    break
        finally:
            self._run_deadline = prior_deadline
        return {"owner": OWNER, "stages_checked": len(receipts), "receipts": receipts,
                "seconds": round(time.monotonic()-started, 3), "status": self.report(persist=False)}

    def tick(self, trigger="manual"):
        try:
            with self.lock():
                self.recover()
                self.observe()  # including after wake; legacy identity check precedes dispatch
                self.resume_daily_review_waits()
                if not self.meta("paused"):
                    # Oldest task whose next engine is not paused; one stage per tick.
                    for row in self.db.execute("SELECT * FROM tasks WHERE state IN ('QUEUED','REWORK','AWAITING_REVIEW') "
                                               "ORDER BY created").fetchall():
                        spec = json.loads(row["spec"])
                        if spec.get("id") != row["id"]:
                            self.state(row["id"], "NEEDS_ATTENTION", "QUEUE_TASK_ID_MISMATCH")
                            continue
                        if "project_binding" in spec:
                            from . import projects
                            dependency = projects.dependency_status(self, spec)
                            if dependency == "WAITING":
                                continue
                            if dependency != "READY":
                                self.state(spec["id"], "NEEDS_ATTENTION", "PROJECT_DEPENDENCY_BLOCKED")
                                continue
                        engine = spec["reviewer"] if row["state"] == "AWAITING_REVIEW" else spec["writer"]
                        if not self.engine_paused(engine):
                            self.process(row)
                            break
                receipt = {"time": utc(), "owner": OWNER, "trigger": trigger, "pid": os.getpid(),
                           "parent_pid": os.getppid(), "source_sha256": manifest(self.root)["sha256"],
                           "paused": self.meta("paused"), "calls_today": self.calls_today(),
                           "engine_pauses": {e: self.engine_paused(e) for e in ENGINES}}
                receipt.update(reviews_today=self.reviews_today(), review_limit=self.policy["daily_review_limit"])
                write_json(self.runtime/"receipts"/(utc().replace(":", "-")+".json"), receipt)
                self.report()
                from . import operations
                operations.refresh_daily(self)
                return receipt
        except Busy:
            return {"skipped": "INSTANCE_ALREADY_RUNNING"}

    def calls_today(self):
        return self.db.execute("SELECT count(*) FROM calls WHERE day=?", (utc()[:10],)).fetchone()[0]

    def report(self, persist=True):
        from . import projects
        tasks = [dict(r) for r in self.db.execute("SELECT id,state,reworks,reason,updated FROM tasks ORDER BY created")]
        value = {"time": utc(), "owner": OWNER, "mode": self.policy["mode"],
                 "paused": self.meta("paused"), "calls_today": self.calls_today(),
                 "reviews_today": self.reviews_today(), "review_limit": self.policy["daily_review_limit"],
                 "reviews_remaining": max(0, self.policy["daily_review_limit"]-self.reviews_today()),
                 "engine_calls_today": {e: self.db.execute(
                     "SELECT count(*) FROM calls JOIN call_engines ON call_engines.call=calls.id "
                     "WHERE calls.day=? AND call_engines.engine=?", (utc()[:10], e)).fetchone()[0] for e in ENGINES},
                 "engine_daily_limits": self.policy["engine_daily_limits"],
                 "engine_pauses": {e: self.engine_paused(e) for e in ENGINES}, "tasks": tasks,
                 "active_source_sha256": manifest(self.root)["sha256"],
                 "enabled": ["observe", *self.policy["actions"]], "research_write": False,
                 "audit_cycle": self.meta("audit_cycle"),
                 "review_cycles": [{"id": r[0], "task": r[1], "state": r[2]} for r in
                                   self.db.execute("SELECT id,task,state FROM review_cycles ORDER BY created")],
                 "gpu": False, "publish": False, "projects": projects.status_cards(self, verify_evidence=False)}
        if not persist:
            return value
        write_json(self.runtime/"STATUS.json", value)
        text = "# ResearchOps status\n\n"+f"UTC: {value['time']}\n\nMode: {value['mode']}\n\nPaused: {value['paused']}\n\nEngine pauses: {value['engine_pauses']}\n\nCalls today: {value['calls_today']} (by engine {value['engine_calls_today']}; local limits {value['engine_daily_limits']})\n\nReviews today: {value['reviews_today']}/{value['review_limit']}\n\n"
        text += "\n".join(f"- {t['id']}: {t['state']} (reworks={t['reworks']}, reason={t['reason']})" for t in tasks)
        (self.runtime/"STATUS.md").write_text(text+"\n", encoding="utf-8")
        return value

    def show(self, task):
        """Read-only view of one task: state, waits, attempts, files and evidence verdicts."""
        row = self.db.execute("SELECT * FROM tasks WHERE id=?", (task,)).fetchone()
        if row is None:
            raise ValueError("Unknown task")
        folder = self.runtime/"tasks"/task
        spec = json.loads(row["spec"])
        wait = self.db.execute("SELECT * FROM task_waits WHERE task=?", (task,)).fetchone()
        attempts = [dict(a) for a in self.db.execute(
            "SELECT id,stage,engine,session,pid,state,created FROM attempts WHERE task=? ORDER BY created", (task,))]
        review = read_json(folder/"review.json")["review"] if (folder/"review.json").exists() else None
        artifact = read_json(folder/"artifact.json") if (folder/"artifact.json").exists() else None
        return {"task": {k: row[k] for k in ("id", "state", "reworks", "reason", "created", "updated")},
                "action": spec["action"], "input": spec["input"], "source_sha256": spec["source"]["sha256"],
                "wait": dict(wait) if wait else None, "attempts": attempts,
                "artifact_checks": (artifact or {}).get("checks"), "artifact_valid_now": (
                    self.valid_artifact(spec, artifact) if artifact is not None else None),
                "review": review, "accepted": (folder/"acceptance.json").exists(),
                "files": sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())[:200]}

    def pause(self, reason="USER_PAUSED"):
        with self.lock():
            self.set_meta("paused", {"reason": reason}, commit=False)
            self.event("DISPATCH_PAUSED", detail={"reason": reason}, commit=False)
            self.db.commit()
            return self.report()

    def resume(self):
        with self.lock():
            self.recover()
            self.observe()
            # Never silently replay quarantined/auth/network/ambiguous attempts.
            previous = self.meta("paused")
            self.set_meta("paused", None, commit=False)
            self.event("DISPATCH_RESUMED", detail={"previous": previous}, commit=False)
            self.db.commit()
            return self.report()

    def requeue_paused(self, task):
        with self.lock():
            row = self.db.execute("SELECT * FROM tasks WHERE id=?", (task,)).fetchone()
            if not row or not row["state"].startswith("PAUSED_"):
                raise ValueError("Only an explicitly paused task can be retried; ambiguous attempts need a new ID")
            a = self.db.execute("SELECT * FROM attempts WHERE task=? ORDER BY created DESC LIMIT 1", (task,)).fetchone()
            if a and a["pid"]:
                live = winproc.identity(a["pid"])
                if live == "UNKNOWN" or live == a["birth"]:
                    raise ValueError("Original process still alive or unidentifiable")
            spec = json.loads(row["spec"])
            previous = self.meta("paused")
            self.retry(spec, "EXPLICIT_RETRY", commit=False)
            self.set_meta("paused", None, commit=False)
            self.event("DISPATCH_RESUMED", task, {"previous": previous, "by": "explicit_retry"}, commit=False)
            self.db.commit()
            return self.report()


def verify_repo(machine):
    root = no_links(machine["expected_repo"])
    if root != REPO or machine["expected_origin"] != ORIGIN:
        raise ValueError("Repository identity mismatch")
    git = machine["git"]
    def get(*args):
        return subprocess.check_output([git, "-C", str(root), *args], text=True, creationflags=0x08000000).strip()
    if Path(get("rev-parse", "--show-toplevel")) != root or get("remote", "get-url", "origin") != ORIGIN:
        raise ValueError("Repository or origin mismatch")
    return {"root": str(root), "origin": ORIGIN, "commit": get("rev-parse", "HEAD")}

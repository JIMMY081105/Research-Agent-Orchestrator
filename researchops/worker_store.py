"""Durable user-initiated Codex turns and approvals, separate from the accepted queue."""
from __future__ import annotations
import datetime as dt
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid

from .dashboard_bundle import safe_path

OWNER = "BGV.Windows.CodexWorker.v1"
MODES = ("approval", "full")
BUSY = ("QUEUED", "STARTING", "RUNNING", "WAITING_APPROVAL", "WAITING_INPUT", "REVIEWING", "CANCELLING", "WAITING_TOOL_EXIT")
SECRET = re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}|(?i:Bearer)\s+[A-Za-z0-9._-]{20,})")


class WorkerError(ValueError):
    def __init__(self, code, status=400):
        super().__init__(code); self.code, self.status = code, status


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def ident(value):
    try:
        if type(value) is not str or str(uuid.UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise WorkerError("INVALID_WORKER_ID") from None
    return value


def clean(value, limit=16000):
    return SECRET.sub("[REDACTED]", str(value))[:limit]


def save(path, value):
    path = safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = safe_path(path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp"))
    with temporary.open("xb") as stream:
        stream.write(canonical(value) + b"\n"); stream.flush(); os.fsync(stream.fileno())
    # CRT readers on Windows may briefly omit FILE_SHARE_DELETE. Retain the
    # complete old record and retry only this owned atomic replacement, bounded.
    deadline = time.monotonic() + .6
    while True:
        try:
            os.replace(temporary, path)
            break
        except OSError as error:
            if getattr(error, 'winerror', None) not in (5, 32, 33) or time.monotonic() >= deadline:
                raise
            time.sleep(.01)


def policy(mode, workspace):
    if mode not in MODES:
        raise WorkerError("INVALID_PERMISSION_MODE")
    if mode == "full":
        return {"approvalPolicy": "never", "sandboxPolicy": {"type": "dangerFullAccess"}}
    return {"approvalPolicy": "untrusted", "sandboxPolicy": {"type": "workspaceWrite",
            "writableRoots": [str(workspace)], "networkAccess": False}}


class Store:
    def __init__(self, runtime, initialize=False):
        self.runtime = safe_path(Path(runtime) / "worker")
        self.db_path = safe_path(self.runtime / "worker.sqlite3")
        if initialize:
            self.runtime.mkdir(parents=True, exist_ok=True)
            with self.db() as db:
                db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, workspace TEXT NOT NULL,
                  thread TEXT, native_session TEXT, model TEXT, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS turns(id TEXT PRIMARY KEY, session TEXT NOT NULL,
                  input_hash TEXT NOT NULL, prompt TEXT NOT NULL, mode TEXT NOT NULL, effort TEXT NOT NULL,
                  skills TEXT NOT NULL, state TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL,
                  native_turn TEXT, response TEXT, reason TEXT, call_id TEXT, reworks INTEGER NOT NULL DEFAULT 0,
                  cancel_requested INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS approvals(id TEXT PRIMARY KEY, turn TEXT NOT NULL, session TEXT NOT NULL,
                  rpc_id TEXT NOT NULL, method TEXT NOT NULL, params TEXT NOT NULL,
                  state TEXT NOT NULL, decision TEXT, created TEXT NOT NULL, updated TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT NOT NULL,
                  turn TEXT, kind TEXT NOT NULL, body TEXT NOT NULL, created TEXT NOT NULL);
                """)
                if 'kind' not in {r[1] for r in db.execute('PRAGMA table_info(turns)')}:
                    db.execute("ALTER TABLE turns ADD COLUMN kind TEXT NOT NULL DEFAULT 'task'")

    @contextlib.contextmanager
    def db(self, read_only=False):
        mode = "ro" if read_only else "rw" if self.db_path.exists() else "rwc"
        db = sqlite3.connect(self.db_path.as_uri() + "?mode=" + mode, uri=True, timeout=3)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=3000")
        try:
            yield db
            if not read_only:
                db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def workspace(self, session):
        return safe_path(self.runtime / "workspaces" / ident(session))

    def _service(self):
        path = safe_path(self.runtime / "service.json")
        try:
            if path.stat().st_size > 128 * 1024:
                return {}
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(data["observed_at"])).total_seconds()
            if data.get("owner") != OWNER or not 0 <= age <= 15 or data.get("state") != "RUNNING":
                return {}
            activation_path = safe_path(self.runtime / "activation.json")
            if not activation_path.exists():
                return {}
            activation = json.loads(activation_path.read_text(encoding="utf-8-sig"))
            if activation.get("owner") != OWNER or activation.get("sha256") != data.get("source_sha256"):
                return {}
            from .dashboard_state import process_identity
            if type(data.get("pid")) is not int or process_identity(data["pid"]) != data.get("birth"):
                return {}
            return data
        except (OSError, ValueError, TypeError, KeyError):
            return {}

    def capability(self):
        from .desktop_recovery import preserve_running_ui_session
        ui_session_migration=preserve_running_ui_session()
        service = self._service()
        paused = any(safe_path(self.runtime / name).exists() for name in ('admission-paused.json', 'review-pause.json', 'stop-when-idle.json'))
        if paused:
            service = {}
        return {"enabled": bool(service), "owner": OWNER, "ui_session_migration":ui_session_migration,"reason": None if service else "WORKER_SERVICE_UNAVAILABLE",
                "modes": list(MODES), "default_mode": "approval", "prompt_chars": 20000,
                "skills": service.get("skills", []), "models": service.get("models", []),
                "default_model": service.get("default_model"), "source_sha256": service.get("source_sha256"),
                "permission_change": "NEXT_TURN_ONLY", "existing_sessions_adopted": False}

    def submit(self, request):
        expected = {"id", "session", "prompt", "mode", "effort", "skills"}
        if type(request) is not dict or not expected <= set(request) <= expected | {'model','kind'}:
            raise WorkerError("INVALID_WORKER_SUBMISSION")
        turn_id = ident(request["id"])
        session = ident(request["session"]) if request["session"] is not None else turn_id
        prompt = request["prompt"]
        if type(prompt) is not str or not prompt.strip() or len(prompt) > 20000 or "\x00" in prompt or SECRET.search(prompt):
            raise WorkerError("INVALID_OR_SENSITIVE_PROMPT")
        if request["mode"] not in MODES or request["effort"] not in ("medium", "high", "xhigh"):
            raise WorkerError("INVALID_WORKER_SETTINGS")
        skills = request["skills"]
        if type(skills) is not list or len(skills) > 8 or any(type(x) is not str for x in skills) or len(set(skills)) != len(skills):
            raise WorkerError("INVALID_WORKER_SKILLS")
        capability = self.capability()
        if not capability["enabled"]:
            raise WorkerError("WORKER_SERVICE_UNAVAILABLE", 503)
        requested_model = request.get('model') or capability['default_model']
        kind=request.get('kind','task')
        if kind not in ('task','analysis'):raise WorkerError('INVALID_WORK_KIND')
        if kind=='analysis' and (request['session'] is not None or request['mode']!='approval'):
            raise WorkerError('ANALYSIS_REQUIRES_FRESH_READ_ONLY_SESSION')
        if request.get('model') and requested_model not in capability.get('models', []):
            raise WorkerError('MODEL_NOT_AVAILABLE')
        names = {x["id"] for x in capability["skills"]}
        if any(x not in names for x in skills):
            raise WorkerError("UNKNOWN_WORKER_SKILL")
        binding = sha(canonical(request))
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT * FROM turns WHERE id=?", (turn_id,)).fetchone()
            if previous:
                if previous["input_hash"] != binding:
                    raise WorkerError("WORKER_ID_INPUT_CONFLICT", 409)
                return {"id": turn_id, "session": previous["session"], "state": previous["state"], "duplicate": True}
            busy = db.execute("SELECT id FROM turns WHERE state IN (" + ",".join("?" for _ in BUSY) + ") LIMIT 1", BUSY).fetchone()
            if busy:
                raise WorkerError("WORKER_BUSY_FINISH_OR_ANSWER_CURRENT_TURN", 409)
            row = db.execute("SELECT * FROM sessions WHERE id=?", (session,)).fetchone()
            if row is None:
                if request["session"] is not None:
                    raise WorkerError("UNKNOWN_WORKER_SESSION", 404)
                db.execute("INSERT INTO sessions(id,workspace,model,created) VALUES(?,?,?,?)",
                           (session, str(self.workspace(session)), requested_model, utc()))
            elif request.get('model') and requested_model != row['model']:
                raise WorkerError('NEW_SESSION_REQUIRED_FOR_MODEL_CHANGE')
            stamp = utc()
            db.execute("INSERT INTO turns(id,session,input_hash,prompt,mode,effort,skills,state,created,updated,kind) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (turn_id, session, binding, prompt, request["mode"], request["effort"], json.dumps(skills), "QUEUED", stamp, stamp,kind))
            folder = safe_path(self.runtime / "turns" / turn_id)
            folder.mkdir(parents=True, exist_ok=False)
            save(folder / "request.json", request)
        return {"id": turn_id, "session": session, "state": "QUEUED", "duplicate": False}

    def event(self, session, turn, kind, body):
        # Deliberate allowlist: no reasoning, hidden analysis, auth tokens or arbitrary protocol dumps.
        if kind not in ("STATUS", "COMMAND", "FILE_CHANGE", "MESSAGE", "REVIEW", "APPROVAL", "INSTRUCTIONS"):
            raise WorkerError("WORKER_EVENT_NOT_ALLOWED")
        with self.db() as db:
            db.execute("INSERT INTO events(session,turn,kind,body,created) VALUES(?,?,?,?,?)",
                       (session, turn, kind, clean(body, 24000), utc()))

    def update(self, turn_id, **values):
        allowed = {"state", "native_turn", "response", "reason", "call_id", "reworks", "cancel_requested"}
        if not values or set(values) - allowed:
            raise WorkerError("INVALID_WORKER_UPDATE")
        values["updated"] = utc()
        with self.db() as db:
            db.execute("UPDATE turns SET " + ",".join(k + "=?" for k in values) + " WHERE id=?",
                       (*values.values(), ident(turn_id)))

    def approval(self, turn, message):
        params, method = message["params"], message["method"]
        if params.get("threadId") != turn["thread"] or params.get("turnId") != turn["native_turn"]:
            raise WorkerError("APPROVAL_SESSION_BINDING_MISMATCH")
        aid = str(uuid.uuid4()); stamp = utc()
        public = {k: params[k] for k in ("command", "cwd", "reason", "grantRoot", "permissions", "questions", "itemId") if k in params}
        encoded = json.dumps(public, ensure_ascii=False)
        if len(encoded) > 24000 or SECRET.search(encoded):
            raise WorkerError("APPROVAL_DETAILS_TOO_LARGE_OR_SENSITIVE")
        with self.db() as db:
            db.execute("INSERT INTO approvals VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (aid, turn["id"], turn["session"], json.dumps(message["id"]), method,
                        encoded, "PENDING", None, stamp, stamp))
        self.update(turn["id"], state="WAITING_INPUT" if "requestUserInput" in method else "WAITING_APPROVAL")
        return aid

    def decide(self, request):
        if (type(request) is not dict or set(request) not in ({"id", "turn", "decision"}, {"id", "turn", "decision", "answers"})
                or request["decision"] not in ("accept", "decline", "cancel", "answer")):
            raise WorkerError("INVALID_APPROVAL_RESPONSE")
        ident(request["id"]); ident(request["turn"])
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT a.*,t.state AS turn_state FROM approvals a JOIN turns t ON t.id=a.turn WHERE a.id=?", (request["id"],)).fetchone()
            if row is None or row["turn"] != request["turn"] or row["turn_state"] not in ("WAITING_APPROVAL", "WAITING_INPUT"):
                raise WorkerError("STALE_APPROVAL", 409)
            if row["method"] == "item/tool/requestUserInput" and request["decision"] == "accept":
                raise WorkerError("USER_INPUT_REQUIRES_TEXT_REPLY")
            decision = request["decision"]
            if decision == "answer":
                questions = json.loads(row["params"]).get("questions", [])
                answers = request.get("answers")
                if (row["method"] != "item/tool/requestUserInput" or type(answers) is not dict
                        or set(answers) != {q["id"] for q in questions}
                        or any(type(x) is not str or not x.strip() or len(x) > 2000 or SECRET.search(x) for x in answers.values())):
                    raise WorkerError("INVALID_USER_ANSWERS")
                decision = json.dumps({"answers": {k: {"answers": [v]} for k, v in answers.items()}}, ensure_ascii=False)
            elif "answers" in request:
                raise WorkerError("UNEXPECTED_ANSWERS")
            if row["state"] != "PENDING":
                if row["decision"] == decision:
                    return {"state": row["state"], "duplicate": True}
                raise WorkerError("APPROVAL_ALREADY_ANSWERED", 409)
            db.execute("UPDATE approvals SET state='ANSWERED',decision=?,updated=? WHERE id=?", (decision, utc(), row["id"]))
        return {"state": "ANSWERED", "duplicate": False}

    def cancel(self, request):
        if type(request) is not dict or set(request) != {"id"}:
            raise WorkerError("INVALID_CANCEL_REQUEST")
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM turns WHERE id=?", (ident(request["id"]),)).fetchone()
            if row is None or row["state"] not in BUSY or row["state"] == "REVIEWING":
                raise WorkerError("OWNED_ACTIVE_TURN_REQUIRED", 409)
            if row["state"] == "QUEUED":
                db.execute("UPDATE turns SET state='CANCELLED',updated=? WHERE id=?", (utc(), row["id"]))
            else:
                db.execute("UPDATE turns SET cancel_requested=1,updated=? WHERE id=?", (utc(), row["id"]))
        return {"state": "CANCEL_REQUESTED"}

    def status(self, session=None):
        capability = self.capability()
        if not self.db_path.exists():
            return {"capability": capability, "sessions": [], "turns": [], "approvals": [], "events": []}
        with self.db(True) as db:
            sessions = [dict(r) for r in db.execute("SELECT * FROM sessions ORDER BY created DESC LIMIT 20")]
            if session is None and sessions:
                session = sessions[0]["id"]
            if session is not None:
                ident(session)
            turns = [dict(r) for r in db.execute("SELECT id,session,prompt,mode,effort,state,created,updated,native_turn,response,reason,reworks FROM turns WHERE session=? ORDER BY created DESC LIMIT 20", (session,))]
            approvals = [dict(r) for r in db.execute("SELECT id,turn,method,params,state FROM approvals WHERE session=? AND state='PENDING' ORDER BY created", (session,))]
            events = [dict(r) for r in db.execute("SELECT id,turn,kind,body,created FROM events WHERE session=? ORDER BY id DESC LIMIT 60", (session,))]
            total = db.execute("SELECT count(*) FROM turns WHERE session=?", (session,)).fetchone()[0]
        for row in approvals:
            row["params"] = json.loads(row["params"])
        events = list(reversed(events))
        from .mission_status import workflow
        return {"capability": capability, "sessions": sessions, "session": session,
                "turns": turns, "approvals": approvals, "events": events,
                "workflow": workflow(self.runtime, turns, sessions, events, total)}


def merge_state(value, runtime):
    """Background sampler only: combine registered worker and legacy queue without claiming external sessions."""
    store = Store(runtime)
    if not store.db_path.exists():
        return value
    status = store.status()
    turns = status["turns"]
    if not turns:
        return value
    turn = turns[0]
    value["worker"] = {"id": turn["id"], "state": turn["state"], "mode": turn["mode"], "available": status["capability"]["enabled"]}
    session = next((s for s in status["sessions"] if s["id"] == turn["session"]), {})
    codex = value.setdefault('engines', {}).setdefault('codex', {})
    codex['last_attempt'] = {'task': turn['id'], 'state': turn['state'], 'session_id': session.get('thread'), 'created': turn['created']}
    try:
        matches = list((store.runtime / 'turns' / turn['id'] / 'reviews').glob('*/result.json'))
        if matches:
            latest = json.loads(safe_path(max(matches, key=lambda x: x.stat().st_mtime)).read_text(encoding='utf-8'))
            value['engines'].setdefault('claude', {})['last_attempt'] = {'task': turn['id'], 'state': latest['status'], 'session_id': latest['session_id'], 'created': latest['created_at']}
    except (OSError, ValueError, KeyError):
        pass
    if turn["state"] not in BUSY or turn["state"] == "QUEUED":
        return value
    from .dashboard_state import process_identity
    engine = "claude" if turn["state"] == "REVIEWING" else "codex"
    record = None
    try:
        if engine == "codex":
            p = store.runtime / "process.json"
        else:
            matches = list((store.runtime / "turns" / turn["id"] / "reviews").glob("*/process.json"))
            p = max(matches, key=lambda x: x.stat().st_mtime) if matches else None
        if p is not None and safe_path(p).stat().st_size <= 128 * 1024:
            record = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    live = (record is not None and type(record.get("pid")) is int and record.get("owner") == OWNER
            and process_identity(record["pid"]) == record.get("birth"))
    e = value.setdefault("engines", {}).setdefault(engine, {})
    existing = list(e.get("active_attempts", []))
    state = "RUNNING" if live and status["capability"]["enabled"] else "UNKNOWN"
    if turn["state"] in ("WAITING_APPROVAL", "WAITING_INPUT"):
        state = "PAUSED"
    session = next((s for s in status["sessions"] if s["id"] == turn["session"]), {})
    e.update(state=state if not existing else e.get("state", state), reason=turn["state"],
             active_attempts=existing + [{"task": turn["id"], "stage": "review" if engine == "claude" else "execute",
               "pid": record.get("pid") if live else None, "birth": record.get("birth") if live else None,
               "session": record.get("session_id") if engine == "claude" and record else session.get("thread"), "created": turn["created"]}])
    return value

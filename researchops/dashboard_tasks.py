"""Fixed analyze_text admission through the verified core CLI, never run/exec.

UI inputs and receipts are separate from the queue. This module reads SQLite in
mode=ro; only the existing frozen controller's submit command may register tasks.
Each ID launches that command at most once, including ambiguous crash recovery.
"""
import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import uuid

from .dashboard_bundle import safe_path, canonical
from .dashboard_state import process_identity

OWNER = "BGV.Windows.SceneControl.Composer.v1"
PYTHON = Path(r"C:\Python312\python.exe")
RUNTIME = Path(r"E:\Github\Building-Generation-Validation\.runtime")
LIMITS = {"prompt_chars": 2000, "context_chars": 12000, "input_bytes": 32768, "request_bytes": 65536}


class TaskError(Exception):
    def __init__(self, code, status=400):
        self.code, self.status = code, status
        super().__init__(code)


def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def identifier(value):
    if type(value) is not str:
        raise TaskError("INVALID_TASK_ID")
    try:
        if str(uuid.UUID(value)) == value:
            return value
    except (ValueError, AttributeError):
        pass
    raise TaskError("INVALID_TASK_ID")


def read_json(path, maximum=2 * 1024 * 1024):
    path = safe_path(path)
    if path.stat().st_size > maximum:
        raise TaskError("METADATA_UNAVAILABLE", 503)
    with path.open("rb") as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise TaskError("METADATA_UNAVAILABLE", 503)
    value = json.loads(data.decode("utf-8-sig"))
    if type(value) is not dict:
        raise TaskError("METADATA_UNAVAILABLE", 503)
    return value


def save(path, value):
    path = safe_path(path)
    temporary = safe_path(path.with_suffix(path.suffix + ".tmp"))
    with temporary.open("wb") as stream:
        stream.write(canonical(value) + b"\n"); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)


@contextlib.contextmanager
def task_lock(path):
    """Cross-process, nonblocking admission lock; never the controller's lock."""
    with safe_path(path).open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0"); stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise TaskError("SUBMISSION_IN_PROGRESS", 409) from None
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def admit(argv, on_start, cwd):
    """No shell, inherited input, raw output, or model call; timeout never means dead."""
    flags = 0x08000000 if os.name == "nt" else 0
    process = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, creationflags=flags)
    birth = process_identity(process.pid)
    on_start(process.pid, birth)
    try:
        return process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        # No Popen context manager: its __exit__ would wait indefinitely here.
        # Do not kill a potentially still-committing submit helper or replay it.
        raise TaskError("CORE_SUBMIT_TIMEOUT", 202) from None


class TaskStore:
    def __init__(self, runtime, admitter=None, identity_probe=process_identity):
        self.runtime = safe_path(runtime)
        if admitter is None and self.runtime != RUNTIME:
            raise ValueError("COMPOSER_RUNTIME_BOUNDARY")
        self.directory = safe_path(self.runtime / "desktop/composer")
        self.admitter = admitter or admit
        self.identity_probe = identity_probe

    def capability(self):
        try:
            self._active()
            return {"enabled": True, "reason": "FIXED_ANALYZE_TEXT_ONLY", "limits": dict(LIMITS),
                    "writers": ["codex", "claude"], "action": "analyze_text",
                    "reviewer_rule": "OTHER_ENGINE", "starts_execution": False}
        except (OSError, ValueError, TypeError, KeyError, TaskError, RecursionError):
            return {"enabled": False, "reason": "VERIFIED_CORE_UNAVAILABLE", "limits": dict(LIMITS)}

    def _active(self):
        record = read_json(self.runtime / "activation.json")
        sha = record.get("source_sha256")
        if record.get("owner") != "BGV.Windows.ResearchOps.v1" or type(sha) is not str or not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise TaskError("VERIFIED_CORE_UNAVAILABLE", 503)
        source = safe_path(self.runtime / "snapshots" / sha / "source")
        if safe_path(record["source"]) != source:
            raise TaskError("VERIFIED_CORE_UNAVAILABLE", 503)
        files = record["source_manifest"]["files"]
        if type(files) is not dict or not 1 <= len(files) <= 256 or digest(canonical(files)) != sha:
            raise TaskError("VERIFIED_CORE_UNAVAILABLE", 503)
        total = 0
        for relative, expected in files.items():
            if (type(relative) is not str or not re.fullmatch(r"[A-Za-z0-9_./-]+", relative)
                    or relative.startswith("/") or any(x in ("", ".", "..") for x in relative.split("/"))):
                raise TaskError("VERIFIED_CORE_UNAVAILABLE", 503)
            path = safe_path(source / relative)
            if path.stat().st_size > 2 * 1024 * 1024:
                raise TaskError("VERIFIED_CORE_UNAVAILABLE", 503)
            total += path.stat().st_size
            if total > 8 * 1024 * 1024 or digest(path.read_bytes()) != expected:
                raise TaskError("VERIFIED_CORE_UNAVAILABLE", 503)
        policy = read_json(source / "config/policy.json", 32768)
        if ("analyze_text" not in policy.get("actions", []) or policy.get("gpu") is not False
                or policy.get("research_write") is not False or policy.get("publish") is not False
                or policy.get("max_input_bytes") != LIMITS["input_bytes"]):
            raise TaskError("ANALYSIS_POLICY_UNAVAILABLE", 503)
        return source, sha

    def _queue(self, task):
        connection = None
        try:
            connection = sqlite3.connect(safe_path(self.runtime / "queue.sqlite3").as_uri() + "?mode=ro", uri=True, timeout=1)
            connection.execute("PRAGMA query_only=ON")
            connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 2 * 1024 * 1024)
            row = connection.execute("SELECT spec,state,reason,created,updated FROM tasks WHERE id=?", (task,)).fetchone()
            return None if row is None else {"spec": json.loads(row[0]), "state": row[1], "reason": row[2], "created": row[3], "updated": row[4]}
        except (sqlite3.Error, ValueError, TypeError, RecursionError):
            raise TaskError("QUEUE_UNAVAILABLE", 503) from None
        finally:
            if connection is not None:
                connection.close()

    def submit(self, request):
        if type(request) is not dict or set(request) != {"id", "prompt", "context", "writer"}:
            raise TaskError("INVALID_SUBMISSION")
        task = identifier(request["id"])
        if (request["writer"] not in ("codex", "claude") or type(request["prompt"]) is not str
                or not request["prompt"].strip() or len(request["prompt"]) > LIMITS["prompt_chars"]
                or type(request["context"]) is not str or len(request["context"]) > LIMITS["context_chars"]):
            raise TaskError("INVALID_SUBMISSION")
        data = {"question": request["prompt"], "text": request["context"] if request["context"].strip() else request["prompt"]}
        if len(canonical(data)) > LIMITS["input_bytes"]:
            raise TaskError("INPUT_TOO_LARGE", 413)
        source, sha = self._active()
        self.directory.mkdir(parents=True, exist_ok=True)
        folder = safe_path(self.directory / task)
        folder.mkdir(exist_ok=True)
        with task_lock(folder / "admission.lock"):
            receipt_path = folder / "receipt.json"
            fingerprint = digest(canonical(request))
            if receipt_path.exists():
                prior = read_json(receipt_path, 16384)
                if prior.get("request_sha256") != fingerprint or prior.get("source_sha256") != sha:
                    raise TaskError("TASK_ID_CONFLICT", 409)
                return {**self.get(task), "duplicate": True}
            if (folder / "input.json").exists() or self._queue(task) is not None:
                raise TaskError("TASK_ID_ALREADY_EXISTS", 409)
            receipt = {"owner": OWNER, "id": task, "request_sha256": fingerprint, "input_sha256": digest(canonical(data)),
                       "source_sha256": sha, "writer": request["writer"], "reviewer": "claude" if request["writer"] == "codex" else "codex",
                       "state": "RECEIVED", "reason": None, "created": stamp(), "updated": stamp(), "admission_reservations": 1}
            save(folder / "receipt.json", receipt)
            save(folder / "input.json", data)
            work = safe_path(folder / "work"); work.mkdir()
            receipt.update(state="SUBMITTING", updated=stamp()); save(receipt_path, receipt)
            argv = [str(PYTHON), "-B", str(source / "researchops.py"), "--root", str(source), "--runtime", str(self.runtime),
                    "--expected-hash", sha, "submit", "--id", task, "--action", "analyze_text", "--input-file", str(folder / "input.json"),
                    "--writer", request["writer"]]
            def started(pid, birth):
                save(folder / "process.json", {"owner": OWNER, "pid": pid, "birth": birth if type(birth) is str and birth.isdigit() else "UNKNOWN", "started_at": stamp()})
            try:
                code = self.admitter(argv, started, work)
                receipt.update(state="REGISTERED" if code == 0 else "SUBMISSION_UNVERIFIED", reason=None if code == 0 else "CORE_SUBMIT_REFUSED")
            except (OSError, ValueError, TaskError, subprocess.SubprocessError):
                receipt.update(state="SUBMISSION_UNVERIFIED", reason="CORE_SUBMIT_UNCERTAIN")
            receipt["updated"] = stamp(); save(receipt_path, receipt)
            return {**self.get(task), "duplicate": False}

    def get(self, task):
        task = identifier(task)
        folder = safe_path(self.directory / task)
        if not (folder / "receipt.json").is_file():
            raise TaskError("TASK_NOT_FOUND", 404)
        receipt = read_json(folder / "receipt.json", 16384)
        if receipt.get("owner") != OWNER or receipt.get("id") != task:
            raise TaskError("TASK_RECEIPT_UNVERIFIED", 409)
        value = {key: receipt.get(key) for key in ("id", "state", "writer", "reviewer", "created", "updated", "reason", "source_sha256")}
        value.update(result=None, result_state="PENDING")
        try:
            queued = self._queue(task)
            if queued is None:
                value.update(state="SUBMISSION_UNVERIFIED", reason="QUEUE_REGISTRATION_NOT_CONFIRMED", result_state="UNVERIFIED")
                process_path = folder / "process.json"
                if process_path.exists():
                    process = read_json(process_path, 8192)
                    if (process.get("owner") == OWNER and type(process.get("pid")) is int and process["pid"] > 0
                            and type(process.get("birth")) is str and process["birth"].isdigit()
                            and self.identity_probe(process["pid"]) == process["birth"]):
                        value.update(state="SUBMISSION_IN_PROGRESS", reason="OWNED_REGISTRATION_PROCESS_ALIVE")
                return value
            spec = queued["spec"]
            if (spec.get("id") != task or spec.get("action") != "analyze_text" or spec.get("input_sha256") != receipt["input_sha256"]
                    or spec.get("writer") != receipt["writer"] or spec.get("source", {}).get("sha256") != receipt["source_sha256"]):
                raise TaskError("QUEUE_BINDING_UNVERIFIED", 409)
            value.update({key: queued[key] for key in ("state", "reason", "created", "updated")})
            if value["state"] == "ACCEPTED":
                source, sha = self._active()
                if sha != receipt["source_sha256"]:
                    raise TaskError("RESULT_SOURCE_CHANGED", 409)
                location = safe_path(self.runtime / "tasks" / task)
                artifact = read_json(location / "artifact.json", 131072)
                acceptance = read_json(location / "acceptance.json", 16384)
                review = read_json(location / "review.json", 32768)
                binding = digest(canonical({"spec": spec, "artifact": artifact}))
                wanted = {"task_id": task, "binding_sha256": binding, "verdict": "PASS", "issues": []}
                text = spec["input"]["text"]
                if (set(artifact) != {"task_id", "input_sha256", "source_sha256", "summary", "citations"}
                        or len(canonical(artifact)) > 65536
                        or any(artifact[key] != expected for key, expected in (("task_id", task), ("input_sha256", receipt["input_sha256"]), ("source_sha256", sha)))
                        or type(artifact["summary"]) is not str or not 10 <= len(artifact["summary"]) <= 5000
                        or type(artifact["citations"]) is not list or not 1 <= len(artifact["citations"]) <= 8
                        or acceptance.get("binding_sha256") != binding or acceptance.get("source_sha256") != sha
                        or acceptance.get("artifact_sha256") != digest(canonical(artifact)) or review.get("review") != wanted
                        or review.get("evidence", {}).get("exit_code") != 0 or review.get("evidence", {}).get("tools_disabled") is not True):
                    raise TaskError("RESULT_UNVERIFIED", 409)
                for cite in artifact["citations"]:
                    if (type(cite) is not dict or set(cite) != {"quote", "start", "end"} or type(cite["start"]) is not int or type(cite["end"]) is not int
                            or not 0 <= cite["start"] < cite["end"] <= len(text) or text[cite["start"]:cite["end"]] != cite["quote"]):
                        raise TaskError("RESULT_UNVERIFIED", 409)
                value.update(result={key: artifact[key] for key in ("summary", "citations")}, result_state="ACCEPTED_BOUND_RESULT")
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, TaskError, RecursionError):
            value.update(result=None, result_state="UNVERIFIED")
            if value.get("state") in ("RECEIVED", "SUBMITTING", "REGISTERED"):
                value.update(state="SUBMISSION_UNVERIFIED", reason="QUEUE_REGISTRATION_NOT_CONFIRMED")
        return value

"""Bounded, read-only dashboard projections. Never dispatch or instantiate System.

Only controller metadata is projected: no task specs, prompts, results, machine
configuration, credentials, raw logs, or model reasoning. Process presence is
not evidence of model activity; a live registered attempt requires PID + birth.
"""
import datetime as dt
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid

OWNER = "BGV.Windows.ResearchOps.v1"
ENGINES = ("codex", "claude")
MAX_TASKS = 100
MAX_ATTEMPTS = 128
MAX_CALLS = 10000
STALE_SECONDS = 1200
_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}(?::[A-Z][A-Z0-9_]{0,63})?\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_BIRTH = re.compile(r"[0-9]{10,24}\Z")


def process_identity(pid):
    """Read creation FILETIME only. None means absent, UNKNOWN means unverified."""
    if os.name != "nt" or type(pid) is not int or not 0 < pid < 2**32:
        return "UNKNOWN"
    import ctypes as c
    from ctypes import wintypes as w
    kernel = c.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.GetExitCodeProcess.argtypes = [w.HANDLE, c.POINTER(w.DWORD)]
    kernel.GetProcessTimes.argtypes = [w.HANDLE, *([c.POINTER(w.FILETIME)] * 4)]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None if c.get_last_error() == 87 else "UNKNOWN"
    try:
        exit_code = w.DWORD()
        if not kernel.GetExitCodeProcess(handle, c.byref(exit_code)):
            return "UNKNOWN"
        if exit_code.value != 259:
            return None
        values = [w.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(c.byref(x) for x in values)):
            return "UNKNOWN"
        return str((values[0].dwHighDateTime << 32) | values[0].dwLowDateTime)
    finally:
        kernel.CloseHandle(handle)


def _path(path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
            raise ValueError("REPARSE_PATH")
    return path


def _json(path, limit=2 * 1024 * 1024):
    path = _path(path)
    if path.stat().st_size > limit:
        raise ValueError("METADATA_TOO_LARGE")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("METADATA_TOO_LARGE")
    value = json.loads(data.decode("utf-8-sig"))
    if type(value) is not dict:
        raise ValueError("INVALID_METADATA")
    return value


def _code(value, default="UNKNOWN"):
    return value if type(value) is str and _CODE.fullmatch(value) else default


def _uuid(value):
    if type(value) is str and len(value) == 36:
        try:
            if str(uuid.UUID(value)) == value:
                return value
        except ValueError:
            pass
    return None


def _date(value):
    if type(value) is not str or len(value) > 64:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(dt.timezone.utc) if parsed.tzinfo else None
    except ValueError:
        return None


def _stamp(value):
    parsed = _date(value)
    return parsed.isoformat() if parsed else None


def _pause(value):
    if value is None:
        return None
    # Only the existence of a pause and a bounded reason code are public.
    return {"reason": _code(value.get("reason")) if type(value) is dict else "UNKNOWN"}


def _attempt(row):
    return {"id": _uuid(row["id"]), "task": _uuid(row["task"]),
            "stage": row["stage"] if row["stage"] in ("execute", "review", "independent-review") else "UNKNOWN",
            "engine": row["engine"] if row["engine"] in ENGINES else "UNKNOWN",
            "session": _uuid(row["session"]),
            "pid": row["pid"] if type(row["pid"]) is int and 0 < row["pid"] < 2**32 else None,
            "birth": row["birth"] if type(row["birth"]) is str and _BIRTH.fullmatch(row["birth"]) else None,
            "state": _code(row["state"]), "created": _stamp(row["created"]),
            "identity_state": "HISTORICAL_NOT_CHECKED"}


def _review(purpose, stage):
    return (stage in ("review", "independent-review")
            or (type(purpose) is str and (purpose.startswith(("independent-review:", "cycle-review:", "codex-audit-dev:"))
                or re.fullmatch(r"[0-9a-f-]{36}:review", purpose) is not None)))


def _observer(runtime, now):
    value = {"observed_at": None, "age_seconds": None, "stale": True,
             "transport": "UNKNOWN", "reason": "OBSERVER_CACHE_UNAVAILABLE",
             "process_counts": {"LIVE": 0, "EXITED": 0, "UNKNOWN": 0},
             "progress_signals": [], "read_only": True,
             "loaded_code_version": "UNVERIFIED", "source": "CONTROLLER_CACHE_ONLY"}
    try:
        report = _json(runtime / "research-watch" / "latest.json")
        observed = _date(report.get("observed_at"))
        if observed is None or observed > now + dt.timedelta(seconds=60):
            raise ValueError("INVALID_CACHE_TIME")
        age = max(0, int((now - observed).total_seconds()))
        value.update(observed_at=observed.isoformat(), age_seconds=age, stale=age > STALE_SECONDS,
                     transport=_code(report.get("transport")), reason=_code(report.get("reason")))
        processes = report.get("processes")
        if type(processes) is not list or len(processes) > 8192:
            raise ValueError("INVALID_PROCESS_CACHE")
        for row in processes:
            status = row.get("state", row.get("status")) if type(row) is dict else "UNKNOWN"
            value["process_counts"][status if status in ("LIVE", "EXITED", "UNKNOWN") else "UNKNOWN"] += 1
        signals = set()
        files = report.get("known_files", [])
        if type(files) is not list or len(files) > 16:
            raise ValueError("INVALID_PROGRESS_CACHE")
        for row in files:
            progress = row.get("progress") if type(row) is dict else None
            candidates = progress.get("signals", []) if type(progress) is dict else []
            if type(candidates) is list:
                signals.update(x for x in candidates[:64] if type(x) is str and x in
                    ("ENTIRE_TASK_STOP_REQUIRED", "CRITICAL_STOP", "FAILED", "COMPLETED", "CHECKPOINT", "RUNNING"))
        value["progress_signals"] = sorted(signals)
        value["read_only"] = report.get("read_only") is True
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        value.update(stale=True, transport="UNKNOWN", reason="OBSERVER_CACHE_UNAVAILABLE",
                     process_counts={"LIVE": 0, "EXITED": 0, "UNKNOWN": 0}, progress_signals=[])
    return value


def read_state(runtime, identity_probe=None, now=None):
    """Return a safe, bounded state projection without any controller side effect.

    ``now`` is an aware datetime, injectable for deterministic tests. The SQLite
    reader holds a short snapshot, never a controller lock. Unregistered CLI
    sessions are deliberately UNKNOWN rather than inferred from executable names.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    if not isinstance(now, dt.datetime) or now.tzinfo is None:
        raise ValueError("Aware datetime required")
    now = now.astimezone(dt.timezone.utc)
    probe = identity_probe or process_identity
    state = {"schema": 1, "observed_at": now.isoformat(), "read_only": True,
             "scope": "REGISTERED_ORCHESTRATOR_TASKS_ONLY",
             "controller": {"owner": OWNER, "database": "UNKNOWN", "reason": "DATABASE_UNAVAILABLE",
                "paused": "UNKNOWN", "source_sha256": None, "active_snapshot": None, "task_counts": {},
                "daily_reviews": {"day": now.date().isoformat(), "used": None, "limit": 50, "remaining": None},
                "calls_today": None, "engine_calls_today": {engine: None for engine in ENGINES}},
             "engines": {engine: {"state": "UNKNOWN", "paused": "UNKNOWN", "active_attempts": [],
                "unverified_attempts": [], "last_attempt": None, "provider_quota": "UNKNOWN"} for engine in ENGINES},
             "mission": {"tasks": [], "active_task_ids": [], "truncated": False},
             "external_sessions": {"state": "UNKNOWN", "unregistered_presence_only": True,
                "reason": "UNREGISTERED_SESSIONS_NOT_PROBED"}}
    try:
        runtime = _path(runtime)
    except (OSError, ValueError):
        state["research_observer"] = _observer(Path(runtime), now)
        return state
    state["research_observer"] = _observer(runtime, now)
    try:
        activation = _json(runtime / "activation.json")
        sha = activation.get("source_sha256")
        if activation.get("owner") == OWNER and type(sha) is str and _SHA.fullmatch(sha):
            state["controller"].update(source_sha256=sha, active_snapshot={"source_sha256": sha,
                "activated_at": _stamp(activation.get("time")), "owner": OWNER})
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        pass
    connection = None
    try:
        database = _path(runtime / "queue.sqlite3")
        connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1)
        connection.row_factory = sqlite3.Row
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 2 * 1024 * 1024)
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        deadline = time.monotonic() + 1
        steps = [0]
        def bounded():
            steps[0] += 1
            return int(steps[0] > 1000 or time.monotonic() > deadline)
        connection.set_progress_handler(bounded, 1000)
        connection.execute("BEGIN")
        counts = connection.execute("SELECT state,count(*) AS count FROM tasks GROUP BY state LIMIT 101").fetchall()
        if len(counts) > 100:
            raise ValueError("TASK_STATE_LIMIT")
        tasks = connection.execute("SELECT id,state,reworks,reason,created,updated FROM tasks ORDER BY created DESC LIMIT ?", (MAX_TASKS + 1,)).fetchall()
        attempts = connection.execute("SELECT id,task,stage,engine,session,pid,birth,state,created FROM attempts WHERE state IN ('RUNNING','STARTING','RESERVED') ORDER BY created DESC LIMIT ?", (MAX_ATTEMPTS + 1,)).fetchall()
        if len(attempts) > MAX_ATTEMPTS:
            raise ValueError("ATTEMPT_LIMIT")
        last = {engine: connection.execute("SELECT id,task,stage,engine,session,pid,birth,state,created FROM attempts WHERE engine=? ORDER BY created DESC LIMIT 1", (engine,)).fetchone() for engine in ENGINES}
        meta = {row["key"]: json.loads(row["value"]) for row in connection.execute(
            "SELECT key,substr(value,1,4096) AS value FROM meta WHERE key IN ('paused','engine_pause:codex','engine_pause:claude')")}
        calls = connection.execute("SELECT substr(c.purpose,1,160) AS purpose,e.stage,e.engine FROM calls c LEFT JOIN call_engines e ON e.call=c.id WHERE c.day=? LIMIT ?", (now.date().isoformat(), MAX_CALLS + 1)).fetchall()
        if len(calls) > MAX_CALLS:
            raise ValueError("CALL_LIMIT")
        connection.rollback()
        reviews = sum(_review(row["purpose"], row["stage"]) for row in calls)
        state["controller"].update(database="OK", reason="READ_ONLY_SNAPSHOT", paused=_pause(meta.get("paused")),
            task_counts={_code(row["state"]): row["count"] for row in counts}, calls_today=len(calls),
            engine_calls_today={engine: sum(row["engine"] == engine for row in calls) for engine in ENGINES},
            daily_reviews={"day": now.date().isoformat(), "used": reviews, "limit": 50, "remaining": max(0, 50 - reviews)})
        state["mission"]["truncated"] = len(tasks) > MAX_TASKS
        state["mission"]["tasks"] = [{"id": _uuid(row["id"]), "state": _code(row["state"]),
            "reworks": row["reworks"] if type(row["reworks"]) is int and 0 <= row["reworks"] <= 2 else None,
            "reason": None if row["reason"] is None else _code(row["reason"]),
            "created": _stamp(row["created"]), "updated": _stamp(row["updated"])} for row in tasks[:MAX_TASKS]]
        for engine in ENGINES:
            target = state["engines"][engine]
            target["paused"] = _pause(meta.get("engine_pause:" + engine))
            target["last_attempt"] = _attempt(last[engine]) if last[engine] else None
            for row in attempts:
                if row["engine"] != engine:
                    continue
                item = _attempt(row)
                try:
                    current = probe(item["pid"]) if item["pid"] and item["birth"] else "UNKNOWN"
                except (OSError, ValueError, TypeError, RuntimeError):
                    current = "UNKNOWN"
                valid = all(item[key] is not None for key in ("id", "task", "session", "pid", "birth"))
                if valid and current == item["birth"]:
                    item["identity_state"] = "VERIFIED_LIVE"
                    created = _date(item["created"])
                    item["elapsed_seconds"] = max(0, int((now - created).total_seconds())) if created else None
                    target["active_attempts"].append(item)
                else:
                    item["identity_state"] = ("UNKNOWN" if not valid else "NOT_LIVE" if current is None else "PID_REUSED" if current != "UNKNOWN" else "UNKNOWN")
                    target["unverified_attempts"].append(item)
            target["state"] = ("RUNNING" if target["active_attempts"] else "STARTING" if any(
                row["state"] in ("STARTING", "RESERVED") and row["pid"] is None for row in target["unverified_attempts"])
                else "UNKNOWN" if target["unverified_attempts"] else "PAUSED" if target["paused"] else "IDLE")
        state["mission"]["active_task_ids"] = sorted({item["task"] for engine in state["engines"].values() for item in engine["active_attempts"]})
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error, UnicodeError, RecursionError):
        state["controller"].update(database="UNKNOWN", reason="DATABASE_UNAVAILABLE")
    finally:
        if connection is not None:
            connection.close()
    return state

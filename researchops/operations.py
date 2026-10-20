"""Controller-owned observation and immutable local daily reports.

The caller MUST hold System.lock. These functions neither acquire that lock nor
call System.report, launch models, modify research, publish, or dispatch tasks.
"""
import datetime as dt
import json
from pathlib import Path
import re
import time
import uuid
from . import evidence, projects, reporting, research_observer
from .integrity import canonical, digest, manifest, no_links, write_json

CADENCE_SECONDS = 900
OWNER = "BGV.Windows.ResearchOps.v1"
_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,95}\Z")
_ID = re.compile(r"[a-z0-9][a-z0-9_.-]{0,119}\Z")


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _code(value, fallback="UNKNOWN"):
    return value if type(value) is str and _CODE.fullmatch(value) else fallback


def _id(value):
    if type(value) is not str or not _ID.fullmatch(value):
        raise evidence.EvidenceError("INVALID_OPERATION_IDENTIFIER")
    return value


def _state(store, relative):
    path = store.path(relative)
    if not path.exists():
        return None
    return store.json(store.fingerprint(relative))


def _save(store, relative, value):
    write_json(store.path(relative), value)


def _configuration(store):
    relative = "research-watch.json"
    path = store.path(relative)
    if not path.exists():
        cfg = {"schema": 1, "enabled": False}
        return cfg, digest(canonical(cfg))
    ref = store.fingerprint(relative)
    cfg = research_observer.validate_configuration(store.json(ref))
    return cfg, ref.sha256


def safe_observer(report):
    """No host/user/IP, arguments, file paths, boot ID, raw logs or SSH metadata."""
    if not isinstance(report, dict):
        report = {}
    counts = {key: 0 for key in ("LIVE", "EXITED", "UNKNOWN")}
    processes = report.get("processes", [])
    if isinstance(processes, list):
        for item in processes:
            state = item.get("state", item.get("status", "UNKNOWN")) if isinstance(item, dict) else "UNKNOWN"
            counts[state if state in counts else "UNKNOWN"] += 1
    signals=set()
    for item in report.get("known_files", []) if type(report.get("known_files")) is list else []:
        if type(item) is dict and type(item.get("progress")) is dict:
            values=item["progress"].get("signals", [])
            for signal in values if type(values) is list else []:
                if signal in ("ENTIRE_TASK_STOP_REQUIRED", "CRITICAL_STOP", "FAILED", "COMPLETED", "CHECKPOINT", "RUNNING"):
                    signals.add(signal)
    return {"transport": _code(report.get("transport")), "reason": _code(report.get("reason")),
            "progress_signals": sorted(signals),
            "process_counts": counts, "read_only": report.get("read_only") is True,
            "model_calls": 0 if report.get("model_calls") == 0 else "UNKNOWN",
            "actions_dispatched": 0 if report.get("actions_dispatched") == 0 else "UNKNOWN", "loaded_code_version": "UNVERIFIED",
            "source_fingerprint": report.get("fingerprint") if evidence.SHA.fullmatch(str(report.get("fingerprint", ""))) else "UNKNOWN"}


def refresh_watch(system, force=False):
    """At most once per 900s unless source/config changed or operator forces it.

    Default config is disabled. observe(System.runtime) is the only observer entry
    point; it owns its fixed read-only helper process and honors the actual config.
    STARTED is persisted before observation so crash/restart does not hot-loop.
    """
    if type(force) is not bool:
        raise ValueError("force must be bool")
    store = evidence.EvidenceStore(system.runtime)
    source = manifest(system.root)["sha256"]
    cfg, config_sha = _configuration(store)
    token = digest(canonical({"source": source, "configuration": config_sha}))
    now = time.time()
    previous = _state(store, "operations/watch-state.json")
    if (not force and previous and previous.get("binding_sha256") == token
            and type(previous.get("started_epoch")) in (int, float)
            and now < previous["started_epoch"] + CADENCE_SECONDS):
        return {"refreshed": False, "changed": False, "reason": "CADENCE_NOT_ELAPSED", "enabled": cfg["enabled"],
                "summary": previous.get("summary"), "previous_state": previous.get("state")}
    record = {"schema": 1, "owner": OWNER, "state": "STARTED", "started_epoch": now,
              "binding_sha256": token, "source_sha256": source, "configuration_sha256": config_sha,
              "enabled": cfg["enabled"], "cadence_seconds": CADENCE_SECONDS}
    _save(store, "operations/watch-state.json", record)
    try:
        report = research_observer.observe(system.runtime)
        summary = safe_observer(report)
        # No raw response, private connection metadata or exception text is copied.
        record.update(state="COMPLETED", summary=summary, changed=report.get("changed") is True)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        record.update(state="FAILED", summary=safe_observer({"reason": "OBSERVATION_FAILED"}), changed=False)
    _save(store, "operations/watch-state.json", record)
    return {"refreshed": True, "changed": record["changed"], "reason": "OBSERVER_DISABLED" if not cfg["enabled"] else record["summary"]["reason"],
            "enabled": cfg["enabled"], "state": record["state"], "summary": record["summary"]}


def _budget(system, day):
    # Calls retain their original rows; no refunds, limit changes or calls are made.
    rows = system.db.execute("SELECT c.purpose,e.stage FROM calls c LEFT JOIN call_engines e ON e.call=c.id WHERE c.day=?", (day,)).fetchall()
    used = sum(stage in ("review", "independent-review") or purpose.startswith(("independent-review:", "cycle-review:", "codex-audit-dev:"))
               or re.fullmatch(r"[0-9a-f-]{36}:review", purpose) is not None for purpose, stage in rows)
    engines = {engine: system.db.execute("SELECT count(*) FROM calls JOIN call_engines ON call_engines.call=calls.id WHERE calls.day=? AND call_engines.engine=?", (day, engine)).fetchone()[0]
               for engine in ("codex", "claude")}
    return {"schema": 1, "day": day, "reviews_today": used, "review_limit": system.policy["daily_review_limit"],
            "engine_calls_today": engines, "calls_today": len(rows), "engine_daily_limits": system.policy["engine_daily_limits"],
            "provider_quota": "UNKNOWN", "source": "READ_ONLY_CALL_LEDGER"}


def _project_summaries(cards):
    rows = []
    for card in cards:
        pid = _id(card["project_id"])
        kind = card.get("kind") if card.get("kind") in ("research", "ops-smoke") else "UNKNOWN"
        tasks = []
        for task in card.get("tasks", []):
            tasks.append({"task_id": _id(task["id"]), "state": _code(task.get("state")),
                          "reason": _code(task.get("reason"), "NONE"),
                          "evidence_state": _code(task.get("content_binding", {}).get("evidence_state")),
                          "scientific_status": "UNVERIFIED"})
        rows.append({"project_id": pid, "profile": _id(card.get("profile", "unknown")), "kind": kind,
                     "state": _code(card.get("state")), "reason": _code(card.get("blocking_reason"), "NONE"),
                     "roles": {"coordinator": "claude", "worker": "codex", "reviewer": "claude", "final_merge": "user"},
                     "active_goal": _id(card["active_goal"]) if card.get("active_goal") else None,
                     "scientific_status": "UNVERIFIED", "tasks": sorted(tasks, key=lambda t: t["task_id"])})
    return sorted(rows, key=lambda p: p["project_id"])


MAX_HISTORY_BYTES = 256 * 1024


def _small_ref(store, relative, expected_sha=None):
    """Bounded metadata only; check size before hashing any bytes."""
    path = store.path(relative)
    if not path.is_file() or path.stat().st_size > MAX_HISTORY_BYTES:
        raise evidence.EvidenceError("HISTORICAL_METADATA_UNAVAILABLE")
    ref = store.fingerprint(relative)
    if expected_sha is not None and ref.sha256 != expected_sha:
        raise evidence.EvidenceError("STALE_HISTORICAL_REFERENCE")
    return ref


def _history_index(store):
    relative = "science-index.json"
    if not store.path(relative).exists():
        return {}
    value = store.json(_small_ref(store, relative), limit=MAX_HISTORY_BYTES)
    if type(value) is not dict or len(value) > 10000:
        raise evidence.EvidenceError("INVALID_CONTROL_INDEX")
    return value


def _historical_science(store, tid, spec, index, source_sha):
    """Small timestamp/hash anchors only. Never inspect or import a cached verdict.

    The reference is explicitly UNVERIFIED even if its historical JSON says READY.
    Referenced large inputs, code/dependency trees and outputs are not revalidated.
    """
    refs = []
    record = {"schema": 1, "kind": "HISTORICAL_SCIENCE_METADATA_ONLY", "task_id": tid,
              "current_source_sha256": source_sha, "historical_accepted_at": "UNKNOWN",
              "recorded_source_sha256": "UNKNOWN", "recorded_input_sha256": "UNKNOWN",
              "verification": "DEFERRED", "scientific_status": "UNVERIFIED",
              "time_meaning": "Historical acceptance timestamp; no current scientific verification."}
    for role in ("source", "input"):
        source = spec.get("source")
        value = source.get("sha256") if role == "source" and type(source) is dict else (
            spec.get("input_sha256") if role == "input" else None)
        if type(value) is str and evidence.SHA.fullmatch(value):
            record["recorded_" + role + "_sha256"] = value
    acceptance_rel = "tasks/" + tid + "/acceptance.json"
    if store.path(acceptance_rel).exists():
        acceptance_ref = _small_ref(store, acceptance_rel)
        acceptance = store.json(acceptance_ref, limit=MAX_HISTORY_BYTES)
        if type(acceptance) is not dict:
            raise evidence.EvidenceError("INVALID_HISTORICAL_ACCEPTANCE")
        stamp = acceptance.get("accepted_at")
        if type(stamp) is str and len(stamp) <= 64:
            try:
                parsed = dt.datetime.fromisoformat(stamp)
                if parsed.tzinfo is not None:
                    record["historical_accepted_at"] = parsed.astimezone(dt.timezone.utc).isoformat()
            except ValueError:
                pass
        record["acceptance"] = acceptance_ref.as_dict()
        refs.append(acceptance_ref)
    if tid in index:
        item = index[tid]
        if type(item) is not dict or set(item) != {"path", "sha256"}:
            raise evidence.EvidenceError("INVALID_CONTROL_INDEX")
        parts = item["path"].split("/") if type(item["path"]) is str else []
        if (len(parts) != 3 or parts[0] != "science-runs" or parts[2] != "report.json"
                or not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", parts[1])
                or type(item["sha256"]) is not str or not evidence.SHA.fullmatch(item["sha256"])):
            raise evidence.EvidenceError("INVALID_CONTROL_INDEX")
        control_ref = _small_ref(store, item["path"], item["sha256"])
        # Never parse the control bundle or trust its cached assessment/process fields.
        record["control_bundle"] = control_ref.as_dict()
        refs.append(control_ref)
    relative = "operations/science-history/" + digest(canonical(record)) + ".json"
    if not store.path(relative).exists():
        _save(store, relative, record)
    elif store.json(_small_ref(store, relative), limit=MAX_HISTORY_BYTES) != record:
        raise evidence.EvidenceError("IMMUTABLE_HISTORY_METADATA_CHANGED")
    refs.append(_small_ref(store, relative))
    return evidence.reference_only(store, tid, "STATIC_GEOMETRY", tuple(refs),
                                   "SCIENTIFIC_REVALIDATION_DEFERRED")


def _retained_science(system, store, verify_science=False):
    tasks = []
    if type(verify_science) is not bool:
        raise ValueError("verify_science must be bool")
    try:
        index = _history_index(store)
        index_valid = True
    except (evidence.EvidenceError, OSError, ValueError, TypeError, KeyError):
        index, index_valid = {}, False
    source_sha = manifest(system.root)["sha256"]
    for row in system.db.execute("SELECT id,spec,state FROM tasks ORDER BY created"):
        tid, raw, state = tuple(row)
        _id(tid)
        try:
            spec = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if not isinstance(spec, dict) or spec.get("action") != "scene_stair_workflow":
            continue
        reason = "SCIENTIFIC_VALIDATION_NOT_EXECUTED"
        static = None
        if state == "ACCEPTED" and not verify_science:
            try:
                if not index_valid:
                    raise evidence.EvidenceError("INVALID_CONTROL_INDEX")
                static = _historical_science(store, tid, spec, index, source_sha)
            except (evidence.EvidenceError, OSError, ValueError, TypeError, KeyError):
                reason = "HISTORICAL_REFERENCE_UNAVAILABLE_REVALIDATION_DEFERRED"
        elif state == "ACCEPTED":
            try:
                if not index_valid:
                    raise evidence.EvidenceError("INVALID_CONTROL_INDEX")
                static = evidence.accepted_static_reference(store, tid)
                if tid in index:
                    from . import science
                    item=index[tid]
                    if type(item) is not dict or set(item)!={"path","sha256"}:
                        raise evidence.EvidenceError("INVALID_CONTROL_INDEX")
                    static=science.reconstruct_assessment(store,evidence.FileRef(item["path"],item["sha256"]))
                    if static.get("sample_id")!=tid or static.get("layer")!="STATIC_GEOMETRY":
                        raise evidence.EvidenceError("FOREIGN_CONTROL_INDEX")
            except (evidence.EvidenceError, OSError, ValueError, TypeError, KeyError):
                static = None
                reason = "RETAINED_STATIC_RECHECK_FAILED"
        layers = [static or evidence.reference_only(store, tid, "STATIC_GEOMETRY", (), reason)]
        layers += [evidence.reference_only(store, tid, layer, (), layer + "_NOT_EXECUTED") for layer in evidence.SCIENCE_LAYERS[1:]]
        tasks.append({"task_id": tid, "owner": "Codex worker Claude reviewer", "stage": "scientific evidence",
                      "assessment": evidence.summarize_sample(tid, layers)})
    return tasks


def _package_valid(store, relative, expected_sha):
    try:
        ref = store.fingerprint(relative + "/package-manifest.json")
        if ref.sha256 != expected_sha:
            return False
        package = store.json(ref)
        if package.get("publish") is not False or not isinstance(package.get("files"), dict):
            return False
        entries = list(store.path(relative).iterdir())
        if {p.name for p in entries} != set(package["files"]) | {"package-manifest.json"} or any(not p.is_file() for p in entries):
            return False
        for name, item in package["files"].items():
            # EvidenceStore vets the whole relative path before opening it.
            path = relative + "/" + name
            if store.fingerprint(path).sha256 != item["sha256"] or store.path(path).stat().st_size != item["bytes"]:
                return False
        return True
    except (evidence.EvidenceError, OSError, KeyError, TypeError):
        return False


def refresh_daily(system, force=False, *, verify_science=False):
    """No lock/report recursion, model, research, network or publication calls.

    Routine refresh exposes bounded historical anchors as UNVERIFIED/DEFERRED.
    Only explicit verify_science=True reconstructs trusted scientific evidence.
    Packages have unique paths and are never overwritten; no cached READY is used.
    """
    if type(force) is not bool or type(verify_science) is not bool:
        raise ValueError("force and verify_science must be bool")
    store = evidence.EvidenceStore(system.runtime)
    day = _now().date().isoformat()
    source_sha = manifest(system.root)["sha256"]
    cards = _project_summaries(projects.status_cards(system, verify_evidence=verify_science))
    watch = _state(store, "operations/watch-state.json") or {}
    observation = watch.get("summary") or safe_observer(None)
    budget = _budget(system, day)
    tasks = _retained_science(system, store, verify_science=verify_science)
    summary = {"schema": 1, "projects": cards, "observer": observation,
               "operational_tasks_are_scientific_evidence": False}
    mode = "TRUSTED_REVALIDATION" if verify_science else "HISTORICAL_REFERENCE_ONLY"
    changed = {"date": day, "source_sha256": source_sha, "summary": summary, "budget": budget,
               "scientific_tasks": tasks, "science_verification": mode}
    fingerprint = digest(canonical(changed))
    previous = _state(store, "operations/daily-state.json")
    if not force and previous and previous.get("fingerprint") == fingerprint:
        if _package_valid(store, previous["output_relative"], previous["manifest_sha256"]):
            return {"refreshed": False, "reason": "NO_MEANINGFUL_CHANGE", **previous}
    if manifest(system.root)["sha256"] != source_sha:
        raise evidence.EvidenceError("SOURCE_CHANGED_DURING_REPORT")
    # Generated ledger snapshot has exact counters, no raw call prompts or outputs.
    budget_rel = "operations/budget/" + digest(canonical(budget)) + ".json"
    if not store.path(budget_rel).exists():
        _save(store, budget_rel, budget)
    elif store.json(store.fingerprint(budget_rel)) != budget:
        raise evidence.EvidenceError("IMMUTABLE_BUDGET_SNAPSHOT_CHANGED")
    output = "daily/" + day + "/" + fingerprint[:16] + "-" + uuid.uuid4().hex
    reporting.create_daily_report(store, output, project="Building Generation Validation", date=day,
                                  tasks=tasks, budget_ref=store.fingerprint(budget_rel),
                                  operational_summary=summary, copy_images=False, publish=False)
    package_ref = store.fingerprint(output + "/package-manifest.json")
    if manifest(system.root)["sha256"] != source_sha:
        raise evidence.EvidenceError("SOURCE_CHANGED_DURING_REPORT")
    record = {"schema": 1, "owner": OWNER, "fingerprint": fingerprint, "date": day,
              "source_sha256": source_sha, "output_relative": output, "manifest_sha256": package_ref.sha256,
              "publish": False, "scientific_status": "UNVERIFIED", "science_verification": mode}
    _save(store, "operations/daily-state.json", record)
    return {"refreshed": True, "reason": "LOCAL_REPORT_CREATED", **record}

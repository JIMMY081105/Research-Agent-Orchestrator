"""Read-only public workflow projection. Never infer a private research plan or reasoning."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .dashboard_bundle import safe_path


PHASES = ("registered", "execute", "review", "result")


def phase_for(state):
    if state == "QUEUED":
        return "registered"
    if state in ("STARTING", "RUNNING", "WAITING_APPROVAL", "WAITING_INPUT", "CANCELLING"):
        return "execute"
    if state == "REVIEWING" or state == "PAUSED_REVIEW":
        return "review"
    if state == "STALLED" or state.startswith("PAUSED_") or state == "INTERRUPTED_NEEDS_RECONCILIATION":
        return "execute"
    if state in ("REVIEW_PASS", "NEEDS_REWORK", "CANCELLED", "INTERRUPTED"):
        return "result"
    return None


def review_summary(worker_root, turn_id):
    """Read only the bounded result record, never packages, prompts or protocol output."""
    try:
        import uuid
        if str(uuid.UUID(turn_id)) != turn_id:
            return None
        directory = safe_path(Path(worker_root) / "turns" / turn_id / "reviews")
        if not directory.is_dir():
            return None
        candidates = []
        for folder in directory.iterdir():
            if not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", folder.name) or not folder.is_dir():
                continue
            if str(uuid.UUID(folder.name)) != folder.name:
                continue
            path = safe_path(folder / "result.json")
            if path.is_file() and path.stat().st_size <= 128 * 1024:
                candidates.append(path)
        if not candidates:
            return None
        path = max(candidates, key=lambda item: item.stat().st_mtime_ns)
        with path.open("rb") as stream:
            data = stream.read(128 * 1024 + 1)
        if len(data) > 128 * 1024:
            return None
        value = json.loads(data)
        if not isinstance(value, dict):
            return None
        text = lambda v, limit=160: v[:limit] if isinstance(v, str) else None
        details = value.get("review") if isinstance(value.get("review"), dict) else {}
        settings = value.get("settings") if isinstance(value.get("settings"), dict) else {}
        evidence = value.get("evidence") if isinstance(value.get("evidence"), dict) else {}
        status = text(value.get("status"))
        if status in ("PASS", "REWORK") and not (
                details.get("verdict") == status
                and isinstance(value.get("binding_sha256"), str)
                and re.fullmatch(r"[0-9a-f]{64}", value["binding_sha256"])
                and details.get("binding_sha256") == value["binding_sha256"]
                and isinstance(details.get("issues"), list)
                and (status != "PASS" or details["issues"] == [])
                and evidence.get("tools_disabled") is True
                and type(evidence.get("exit_code")) is int and evidence["exit_code"] == 0):
            status = "UNVERIFIED"
        issues = details.get("issues", [])
        return {"id": path.parent.name, "status": status,
                "created_at": text(value.get("created_at")),
                "completed_at": text(value.get("completed_at")),
                "session_id": text(value.get("session_id")),
                "model": text(settings.get("model")), "effort": text(settings.get("effort")),
                "permission_mode": text(settings.get("permission_mode")),
                "tools_disabled": settings.get("tools_disabled") is True,
                "issues": [item[:1500] for item in issues[:20] if isinstance(item, str)]
                if isinstance(issues, list) else [],
                "scope": text(value.get("scope"))}
    except (OSError, ValueError, TypeError, KeyError):
        return None


def workflow(worker_root, turns, sessions, events, total):
    """A turn is an execution/review cycle; it is not a made-up master-goal stage."""
    session_models = {row["id"]: row.get("model") for row in sessions}
    stages = []
    for turn in reversed(turns):
        stages.append({"id": turn["id"], "state": turn["state"],
                       "phase": phase_for(turn["state"]),
                       "created": turn["created"], "updated": turn["updated"],
                       "model": session_models.get(turn["session"]),
                       "effort": turn["effort"], "permission_mode": turn["mode"],
                       "review": review_summary(worker_root, turn["id"])})
    return {"source": "REGISTERED_OWNED_TURNS", "phases": list(PHASES),
            "stages": stages, "total_turns": total, "displayed_turns": len(turns),
            "current_turn_id": turns[0]["id"] if turns else None,
            "master_plan": None, "events": events,
            "reasoning_available": False}

"""Local GitHub-ready review bundles. No publish/network/credential or model operations.

Only generated summaries enter the bundle. Runtime evidence stays reference-only;
copyright-unknown images are never copied. A status diagram is not a research render.
"""
from dataclasses import dataclass
import datetime as dt
import html
import json
from pathlib import Path
import re
import struct
import zlib
from .evidence import CODE, SCIENCE_LAYERS, EvidenceError, EvidenceStore, FileRef, SHA, STATUSES, canonical, digest, issued_assessment

REPORTING_SHA256 = digest(Path(__file__).read_bytes())


def label(value):
    if type(value) is not str or not 1 <= len(value) <= 120 or any(not (c.isalnum() or c in " _.-/") for c in value):
        raise EvidenceError("UNSAFE_REPORT_LABEL")
    return value


@dataclass(frozen=True)
class RenderImage:
    image: FileRef
    capture: FileRef
    run_id: str
    view_id: str
    mode: str
    asset_sha256: str
    camera_sha256: str
    rights: str = "UNKNOWN"
    copy_permission: FileRef | None = None


@dataclass(frozen=True)
class ImagePair:
    view_id: str
    beauty: RenderImage | None = None
    collision: RenderImage | None = None


def png_info(store, ref):
    """Conservative stdlib PNG validation: supported 8-bit RGB/RGBA, complete CRC/rows.

    It does not claim target/collider visibility or prove a simulation was run.
    Other image encodings remain UNVERIFIED rather than silently passing.
    """
    store.verify(ref)
    path = store.path(ref.path)
    if path.stat().st_size > 16 * 1024 * 1024:
        raise EvidenceError("IMAGE_TOO_LARGE")
    raw = path.read_bytes()
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise EvidenceError("UNSUPPORTED_IMAGE_FORMAT")
    offset, compressed, dimensions, ended = 8, bytearray(), None, False
    while offset < len(raw):
        if offset + 12 > len(raw):
            raise EvidenceError("TRUNCATED_IMAGE")
        size = struct.unpack_from(">I", raw, offset)[0]
        kind = raw[offset+4:offset+8]
        if offset == 8 and kind != b"IHDR":
            raise EvidenceError("INVALID_IMAGE_HEADER")
        end = offset + 12 + size
        if end > len(raw):
            raise EvidenceError("TRUNCATED_IMAGE")
        data = raw[offset+8:offset+8+size]
        crc = struct.unpack_from(">I", raw, offset+8+size)[0]
        if zlib.crc32(kind + data) & 0xffffffff != crc:
            raise EvidenceError("INVALID_IMAGE_CRC")
        if kind == b"IHDR":
            if dimensions is not None or offset != 8 or size != 13:
                raise EvidenceError("INVALID_IMAGE_HEADER")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", data)
            if not (16 <= width <= 4096 and 16 <= height <= 4096 and depth == 8 and color in (2, 6) and compression == filtering == interlace == 0):
                raise EvidenceError("UNSUPPORTED_IMAGE_LAYOUT")
            dimensions = (width, height, 3 if color == 2 else 4)
        elif kind == b"IDAT":
            compressed.extend(data)
        elif kind == b"IEND":
            if size != 0 or end != len(raw):
                raise EvidenceError("INVALID_IMAGE_END")
            ended = True
        elif not (kind[0] & 32):
            raise EvidenceError("UNSUPPORTED_IMAGE_CRITICAL_CHUNK")
        offset = end
    if not dimensions or not ended or not compressed:
        raise EvidenceError("INCOMPLETE_IMAGE")
    width, height, channels = dimensions
    expected = height * (1 + width * channels)
    decoder = zlib.decompressobj()
    try:
        pixels = decoder.decompress(compressed, expected + 1)
    except zlib.error:
        raise EvidenceError("INVALID_IMAGE_DATA")
    if len(pixels) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise EvidenceError("INVALID_IMAGE_DATA")
    stride = 1 + width * channels
    if any(pixels[i] > 4 for i in range(0, len(pixels), stride)):
        raise EvidenceError("INVALID_IMAGE_FILTER")
    # Reconstruct PNG filters: a uniformly coloured image may have many encoded byte values.
    previous = bytearray(width * channels)
    first, different, visible = None, 0, 0
    for row_index in range(height):
        start = row_index * stride
        kind = pixels[start]
        row = bytearray(pixels[start+1:start+stride])
        for j in range(len(row)):
            left = row[j-channels] if j >= channels else 0
            above = previous[j]
            corner = previous[j-channels] if j >= channels else 0
            if kind == 1:
                predictor = left
            elif kind == 2:
                predictor = above
            elif kind == 3:
                predictor = (left + above) // 2
            elif kind == 4:
                estimate = left + above - corner
                distances = (abs(estimate-left), abs(estimate-above), abs(estimate-corner))
                predictor = (left, above, corner)[distances.index(min(distances))]
            else:
                predictor = 0
            row[j] = (row[j] + predictor) & 255
        for j in range(0, len(row), channels):
            if channels == 4 and row[j+3] == 0:
                continue
            visible += 1
            color = bytes(row[j:j+3])
            if first is None:
                first = color
            elif color != first:
                different += 1
        previous = row
    if visible < max(4, width * height // 1000) or different < max(2, width * height // 1000):
        raise EvidenceError("BLANK_OR_TRIVIAL_IMAGE")
    return {"width": width, "height": height, "encoding": "PNG", "semantic_visibility": "UNVERIFIED"}


def inspect_pair(store, pair, trusted_runs):
    label(pair.view_id)
    for image in (pair.beauty, pair.collision):
        if image is not None:
            store.path(image.image.path)
            if not SHA.fullmatch(image.image.sha256) or image.rights not in ("UNKNOWN", "USER_OWNED", "LICENSED_FOR_REPORT"):
                raise EvidenceError("INVALID_IMAGE_REFERENCE")
    refs = [x.image.as_dict() for x in (pair.beauty, pair.collision) if x is not None]
    if pair.beauty is None or pair.collision is None:
        return {"view_id": pair.view_id, "status": "MISSING", "reason": "BEAUTY_OR_COLLISION_NOT_PROVIDED", "references": refs}
    try:
        for image, mode in ((pair.beauty, "BEAUTY"), (pair.collision, "COLLISION")):
            if image.view_id != pair.view_id or image.mode != mode or not SHA.fullmatch(image.asset_sha256) or not SHA.fullmatch(image.camera_sha256):
                raise EvidenceError("IMAGE_IDENTITY_MISMATCH")
            run = trusted_runs.get(image.run_id)
            if not run or run.receipt != image.capture or run.completed is not True or type(run.exit_code) is not int or run.exit_code != 0 or run.process_verified is not True or image.image not in run.binding.artifacts:
                raise EvidenceError("UNTRUSTED_IMAGE_CAPTURE")
            run.binding.verify(store)
            capture = store.json(image.capture)
            expected = {"kind": "RENDER_CAPTURE", "view_id": image.view_id, "mode": mode,
                        "asset_sha256": image.asset_sha256, "camera_sha256": image.camera_sha256,
                        "image_sha256": image.image.sha256, "completed": True}
            if any(capture.get(k) != v for k, v in expected.items()):
                raise EvidenceError("IMAGE_CAPTURE_BINDING_MISMATCH")
            png_info(store, image.image)
        if pair.beauty.asset_sha256 != pair.collision.asset_sha256 or pair.beauty.camera_sha256 != pair.collision.camera_sha256:
            raise EvidenceError("IMAGE_PAIR_ASSET_OR_CAMERA_MISMATCH")
        if pair.beauty.image.sha256 == pair.collision.image.sha256:
            raise EvidenceError("DUPLICATE_BEAUTY_COLLISION_IMAGE")
    except EvidenceError as error:
        return {"view_id": pair.view_id, "status": "UNVERIFIED", "reason": error.reason, "references": refs}
    except Exception:
        return {"view_id": pair.view_id, "status": "UNVERIFIED", "reason": "IMAGE_VALIDATION_ERROR", "references": refs}
    return {"view_id": pair.view_id, "status": "PAIRED_RUNTIME_CAPTURE", "reason": "MATCHING_ASSET_AND_CAMERA",
            "references": refs, "semantic_collider_visibility": "UNVERIFIED", "proves_robot_behavior": False,
            "rights": [pair.beauty.rights, pair.collision.rights]}


def _copy_allowed(store, image):
    if image.rights not in ("USER_OWNED", "LICENSED_FOR_REPORT") or image.copy_permission is None:
        return False
    permission = store.json(image.copy_permission)
    return (permission.get("image_sha256") == image.image.sha256 and permission.get("permission") == "COPY_FOR_LOCAL_REPORT"
            and type(permission.get("authority")) is str and bool(permission["authority"].strip()))


def _check_result_references(store, value):
    """Formatting never upgrades a verdict, and stale referenced evidence refuses the report."""
    allowed = {"status", "reason", "evidence", "layer", "sample_id", "gate_id", "binding_sha256", "controls",
               "case_count", "seeds", "seed_policy", "scope", "layers", "missing_layers", "expected_ids",
               "denominator", "observed_count", "ready_count", "counts", "missing_ids", "samples", "evaluator_sha256",
               "binding", "control_bindings", "legacy_static_accepted"}
    if (not issued_assessment(value) or value.get("status") not in STATUSES or set(value)-allowed
            or type(value.get("reason")) is not str or not CODE.fullmatch(value["reason"])):
        raise EvidenceError("INVALID_ASSESSMENT")
    if "scope" in value and value["scope"] not in ("SINGLE_SAMPLE_SINGLE_LAYER", "SINGLE_SAMPLE_ALL_SCIENTIFIC_LAYERS", "EXACT_DECLARED_BATCH"):
        raise EvidenceError("INVALID_ASSESSMENT_SCOPE")
    for key in ("sample_id", "gate_id", "layer"):
        if key in value:
            label(value[key])
    if "binding_sha256" in value and not SHA.fullmatch(value["binding_sha256"]):
        raise EvidenceError("INVALID_BINDING_HASH")
    if "evaluator_sha256" in value and not SHA.fullmatch(value["evaluator_sha256"]):
        raise EvidenceError("INVALID_EVALUATOR_HASH")
    if "legacy_static_accepted" in value and type(value["legacy_static_accepted"]) is not bool:
        raise EvidenceError("INVALID_LEGACY_REFERENCE")
    if "controls" in value and (type(value["controls"]) is not dict or set(value["controls"]) != {"positive", "negative", "negative_reason"}
            or value["controls"]["positive"] != "PASS" or value["controls"]["negative"] != "EXPECTED_FAIL"
            or not CODE.fullmatch(value["controls"]["negative_reason"])):
        raise EvidenceError("INVALID_CONTROL_SUMMARY")
    for key in ("case_count", "denominator", "observed_count", "ready_count"):
        if key in value and (type(value[key]) is not int or not 0 <= value[key] <= 1000000):
            raise EvidenceError("INVALID_ASSESSMENT_COUNT")
    for key in ("seeds", "expected_ids", "missing_ids", "missing_layers"):
        if key in value:
            if type(value[key]) is not list or len(value[key]) > 10000:
                raise EvidenceError("INVALID_ASSESSMENT_ARRAY")
            if key == "seeds":
                if any(type(seed) is not int or abs(seed) > 10**18 for seed in value[key]):
                    raise EvidenceError("INVALID_ASSESSMENT_SEEDS")
            else:
                for text in value[key]:
                    label(text)
    if "seed_policy" in value and value["seed_policy"] not in ("seeded", "deterministic"):
        raise EvidenceError("INVALID_SEED_POLICY")
    if "counts" in value and (set(value["counts"]) != set(STATUSES) or any(type(n) is not int or not 0 <= n <= 1000000 for n in value["counts"].values())):
        raise EvidenceError("INVALID_ASSESSMENT_COUNT")
    for ref in value.get("evidence", []):
        if type(ref) is not dict or set(ref) != {"path", "sha256"}:
            raise EvidenceError("INVALID_FILE_REFERENCE")
        store.verify(FileRef(ref["path"], ref["sha256"]))
    bindings = []
    if "binding" in value:
        if digest(canonical(value["binding"])) != value.get("binding_sha256"):
            raise EvidenceError("INVALID_BINDING_HASH")
        bindings.append(value["binding"])
    if "control_bindings" in value:
        if type(value["control_bindings"]) is not dict or set(value["control_bindings"]) != {"positive", "negative"}:
            raise EvidenceError("INVALID_CONTROL_BINDINGS")
        bindings.extend(value["control_bindings"].values())
    for binding in bindings:
        if type(binding) is not dict or set(binding) != {"source", "inputs", "artifacts"}:
            raise EvidenceError("INVALID_ASSESSMENT_BINDING")
        for refs in binding.values():
            if type(refs) is not list or not refs:
                raise EvidenceError("INVALID_ASSESSMENT_BINDING")
            for ref in refs:
                if type(ref) is not dict or set(ref) != {"path", "sha256"}:
                    raise EvidenceError("INVALID_FILE_REFERENCE")
                store.verify(FileRef(ref["path"], ref["sha256"]))
    if set(value.get("layers", {}))-set(SCIENCE_LAYERS):
        raise EvidenceError("INVALID_ASSESSMENT_LAYER")
    for nested in value.get("layers", {}).values():
        _check_result_references(store, nested)
    for nested in value.get("samples", []):
        _check_result_references(store, nested)
    if value["status"] == "READY":
        if value.get("scope") == "SINGLE_SAMPLE_SINGLE_LAYER":
            if not value.get("evidence") or value.get("controls", {}).get("negative") != "EXPECTED_FAIL" or not SHA.fullmatch(value.get("binding_sha256", "")):
                raise EvidenceError("UNBOUND_READY_ASSESSMENT")
        elif value.get("scope") == "SINGLE_SAMPLE_ALL_SCIENTIFIC_LAYERS":
            if set(value.get("layers", {})) != set(SCIENCE_LAYERS) or any(r.get("status") != "READY" for r in value["layers"].values()):
                raise EvidenceError("UNBOUND_READY_ASSESSMENT")
        elif value.get("scope") == "EXACT_DECLARED_BATCH":
            from .evidence import summarize_batch
            expected = summarize_batch(value.get("expected_ids", []), value.get("samples", []), value.get("denominator"))
            if expected != value or expected["status"] != "READY":
                raise EvidenceError("UNBOUND_READY_ASSESSMENT")
        else:
            raise EvidenceError("UNBOUND_READY_ASSESSMENT")


def _operations(value):
    """Strict generated-summary schema; never accept raw observer/project dictionaries."""
    if value is None:
        return None
    if type(value) is not dict or set(value) != {"schema", "projects", "observer", "operational_tasks_are_scientific_evidence"} or value["schema"] != 1 or value["operational_tasks_are_scientific_evidence"] is not False:
        raise EvidenceError("INVALID_OPERATIONAL_SUMMARY")
    observer = value["observer"]
    if (type(observer) is not dict or set(observer) != {"transport", "reason", "process_counts", "read_only", "model_calls", "actions_dispatched", "loaded_code_version", "source_fingerprint", "progress_signals"}
            or observer["model_calls"] not in (0, "UNKNOWN") or observer["actions_dispatched"] not in (0, "UNKNOWN")
            or type(observer["read_only"]) is not bool or observer["loaded_code_version"] != "UNVERIFIED"
            or not (observer["source_fingerprint"] == "UNKNOWN" or SHA.fullmatch(str(observer["source_fingerprint"])))):
        raise EvidenceError("INVALID_OBSERVER_SUMMARY")
    if (type(observer["progress_signals"]) is not list or len(observer["progress_signals"])>6
            or any(s not in ("ENTIRE_TASK_STOP_REQUIRED", "CRITICAL_STOP", "FAILED", "COMPLETED", "CHECKPOINT", "RUNNING") for s in observer["progress_signals"])):
        raise EvidenceError("INVALID_OBSERVER_SUMMARY")
    if any(not CODE.fullmatch(str(observer[k])) for k in ("transport", "reason")):
        raise EvidenceError("INVALID_OBSERVER_SUMMARY")
    counts = observer["process_counts"]
    if type(counts) is not dict or set(counts) != {"LIVE", "EXITED", "UNKNOWN"} or any(type(n) is not int or n < 0 for n in counts.values()):
        raise EvidenceError("INVALID_OBSERVER_SUMMARY")
    if type(value["projects"]) is not list or len(value["projects"]) > 100:
        raise EvidenceError("INVALID_PROJECT_SUMMARY")
    ids = set()
    for p in value["projects"]:
        if type(p) is not dict or set(p) != {"project_id", "profile", "kind", "state", "reason", "roles", "active_goal", "scientific_status", "tasks"}:
            raise EvidenceError("INVALID_PROJECT_SUMMARY")
        for k in ("project_id", "profile", "state", "reason"):
            label(p[k])
        if p["active_goal"] is not None:
            label(p["active_goal"])
        if p["project_id"] in ids or p["kind"] not in ("research", "ops-smoke", "UNKNOWN") or p["scientific_status"] != "UNVERIFIED" or p["roles"] != {"coordinator": "claude", "worker": "codex", "reviewer": "claude", "final_merge": "user"} or type(p["tasks"]) is not list:
            raise EvidenceError("INVALID_PROJECT_SUMMARY")
        ids.add(p["project_id"])
        tasks = set()
        for t in p["tasks"]:
            if type(t) is not dict or set(t) != {"task_id", "state", "reason", "evidence_state", "scientific_status"} or t["scientific_status"] != "UNVERIFIED" or t["task_id"] in tasks:
                raise EvidenceError("INVALID_OPERATIONAL_TASK")
            for k in ("task_id", "state", "reason", "evidence_state"):
                label(t[k])
            tasks.add(t["task_id"])
    return value


def create_daily_report(store: EvidenceStore, output_relative, *, project, date, tasks, budget_ref,
                        image_pairs=(), expected_views=("overview",), trusted_runs=None,
                        copy_images=False, publish=False, operational_summary=None):
    """Create a concrete local review bundle, never a push/PR or a runtime directory dump.

    `tasks` are trusted-controller results of evidence.summarize_sample, not model JSON.
    Each row has task_id, owner, stage, assessment. Existing files are not overwritten.
    """
    if publish is not False:
        raise EvidenceError("PUBLISH_NOT_AUTHORIZED")
    operational_summary = _operations(operational_summary)
    label(project)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise EvidenceError("INVALID_REPORT_DATE")
    try:
        dt.date.fromisoformat(date)
    except ValueError:
        raise EvidenceError("INVALID_REPORT_DATE")
    if not expected_views or len(set(expected_views)) != len(expected_views):
        raise EvidenceError("INVALID_VIEW_CONTRACT")
    for view in expected_views:
        label(view)
    trusted_runs = trusted_runs or {}
    budget = store.json(budget_ref)
    used, limit = budget.get("reviews_today"), budget.get("review_limit")
    if type(used) is not int or used < 0 or limit != 50:
        raise EvidenceError("UNVERIFIED_BUDGET_SNAPSHOT")
    calls = budget.get("engine_calls_today", {})
    if set(calls) != {"codex", "claude"} or any(type(v) is not int or v < 0 for v in calls.values()):
        raise EvidenceError("UNVERIFIED_BUDGET_SNAPSHOT")
    rows, ids = [], set()
    for row in tasks:
        tid = label(row["task_id"])
        if tid in ids:
            raise EvidenceError("DUPLICATE_REPORT_TASK_ID")
        ids.add(tid)
        _check_result_references(store, row["assessment"])
        rows.append({"task_id": tid, "owner": label(row["owner"]), "stage": label(row["stage"]), "assessment": row["assessment"]})
    pairs = list(image_pairs)
    if len({p.view_id for p in pairs}) != len(pairs) or set(p.view_id for p in pairs) - set(expected_views):
        raise EvidenceError("UNEXPECTED_OR_DUPLICATE_VIEW_ID")
    by_view = {p.view_id: p for p in pairs}
    images = [inspect_pair(store, by_view.get(v, ImagePair(v)), trusted_runs) for v in expected_views]
    payloads = {}
    for image, pair in zip(images, (by_view.get(v) for v in expected_views)):
        image["copied"] = []
        if pair and image["status"] == "PAIRED_RUNTIME_CAPTURE" and copy_images:
            for role, source in (("beauty", pair.beauty), ("collision", pair.collision)):
                if _copy_allowed(store, source):
                    name = "images/" + source.image.sha256 + ".png"
                    data = store.path(source.image.path).read_bytes()
                    if digest(data) != source.image.sha256:
                        raise EvidenceError("STALE_FILE_HASH")
                    payloads[name] = data
                    image["copied"].append({"role": role, "path": name})
        image["reference_only"] = not bool(image["copied"])
    index = {"schema": 1, "project": project, "date": date, "publish": False, "generator_sha256": REPORTING_SHA256,
             "scope": "LOCAL_REVIEW_BUNDLE", "tasks": rows,
             "models": {"review_used": used, "review_limit": limit, "review_remaining": max(0, limit-used),
                        "review_budget_exhausted": used >= limit, "engine_calls": calls,
                        "execution_local_daily_cap": None, "provider_quota": "UNKNOWN", "evidence": budget_ref.as_dict()},
             "images": images, "raw_runtime_or_model_output_included": False}
    if operational_summary is not None:
        index["operations"] = operational_summary
    lines = [f"# {project} — {date} (UTC)", "", "Local review bundle · date and budget day use UTC · publish=false · no GitHub upload performed.", "",
             f"Reviews: {used}/{limit}; remaining {max(0, limit-used)}. Provider quota: UNKNOWN.", "",
             "| Task | Owner | Stage | Status | Reason |", "|---|---|---|---|---|"]
    for row in rows:
        result = row["assessment"]
        lines.append(f"| {row['task_id']} | {row['owner']} | {row['stage']} | {result['status']} | {result['reason']} |")
        for layer, item in result.get("layers", {}).items():
            lines.append(f"| {row['task_id']} / {layer} | {row['owner']} | evidence | {item['status']} | {item['reason']} |")
            if item.get("legacy_static_accepted") is True:
                lines.append(f"| {row['task_id']} / retained CPU static | {row['owner']} | historical acceptance | ACCEPTED (retained) | Existing accepted files/hashes rechecked; no new native/nav/behavior claim |")
    if operational_summary is not None:
        observer = operational_summary["observer"]
        lines += ["", "## Project operations", "", "Operational acceptance is not scientific validation. All unperformed scientific layers remain UNVERIFIED.", "",
                  "Coordinator/reviewer: Claude; worker: Codex; final merge: user.", "",
                  "| Project | Profile | Kind | State | Reason | Scientific |", "|---|---|---|---|---|---|"]
        for p in operational_summary["projects"]:
            lines.append(f"| {p['project_id']} | {p['profile']} | {p['kind']} | {p['state']} | {p['reason']} | UNVERIFIED |")
        lines.append("")
        for p in operational_summary["projects"]:
            for t in p["tasks"]:
                lines.append(f"- Task {t['task_id']}: {t['state']}; {t['reason']}; operational evidence {t['evidence_state']}; scientific UNVERIFIED.")
        lines += ["", f"Read-only observer: {observer['transport']}; {observer['reason']}; process counts {observer['process_counts']}; loaded code version UNVERIFIED.",
                  f"Registered-file progress signals: {observer['progress_signals']}; signals alone do not establish task completion.",
                  "Observer host/user/IP, SSH configuration, arguments, absolute paths, boot IDs and raw logs are excluded."]
    lines += ["", "## Beauty / Collision", "", "Images below are only existing verified captures; missing images remain MISSING.", ""]
    for image in images:
        lines.append(f"- {image['view_id']}: **{image['status']}** — {image['reason']}; semantic collider visibility: UNVERIFIED.")
        for ref in image["references"]:
            lines.append(f"  - Runtime reference only: `{ref['path']}` · SHA256 `{ref['sha256']}`")
        for copied in image["copied"]:
            lines.append(f"  - {copied['role']}: ![{copied['role']}]({copied['path']})")
    lines += ["", "## Evidence", "", f"Budget: `{budget_ref.path}` · SHA256 `{budget_ref.sha256}`", ""]
    for row in rows:
        assessments = row["assessment"].get("layers", {"summary": row["assessment"]})
        for layer, assessment in assessments.items():
            references = assessment.get("evidence", [])
            lines.append(f"- {row['task_id']} / {layer}: {len(references)} bound file references; complete identities in index.json.")
            for ref in references[:8]:
                lines.append(f"  - `{ref['path']}` · SHA256 `{ref['sha256']}`")
    lines += ["", "Only generated summaries and explicitly permitted images are packaged. Source, raw model output, credentials, machine configuration and the full runtime stay outside this bundle.", "",
              "`status.svg` is a generated status diagram, not a scene render or collision/robot test."]
    counts = {status: sum(r["assessment"]["status"] == status for r in rows) for status in STATUSES}
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="700" height="170" role="img" aria-label="Task status summary">'
    svg += '<rect width="700" height="170" fill="#10202b"/><g fill="#ffffff" font-family="sans-serif" font-size="18">'
    svg += '<text x="20" y="30">Local task status — not a research render</text>'
    for i, status in enumerate(STATUSES):
        svg += f'<text x="20" y="{60+i*25}">{html.escape(status)}: {counts[status]}</text>'
    svg += '</g></svg>'
    payloads.update({"REPORT.md": ("\n".join(lines)+"\n").encode("utf-8"), "index.json": canonical(index)+b"\n", "status.svg": svg.encode("utf-8")})
    package = {"schema": 1, "publish": False, "files": {name: {"sha256": digest(data), "bytes": len(data)} for name, data in sorted(payloads.items())},
               "excluded": ["credentials", "machine configuration", "raw model output", "complete runtime", "unknown-rights images"],
               "evidence_payloads_copied": False}
    payloads["package-manifest.json"] = canonical(package)+b"\n"
    store.verify(budget_ref)
    for row in rows:
        _check_result_references(store, row["assessment"])
    for pair in pairs:
        for image in (pair.beauty, pair.collision):
            if image is not None and image.image.path in {r["path"] for r in next(i for i in images if i["view_id"] == pair.view_id)["references"]}:
                if store.path(image.image.path).is_file():
                    store.verify(image.image)
    output = store.path(output_relative)
    output.mkdir(parents=True, exist_ok=False)
    for name, data in payloads.items():
        target = output.joinpath(*name.split("/"))
        store._no_links(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
    return {"output": output_relative, "manifest": package, "index": index, "publish": False}

"""Actual native-window verification; fixture evidence never proves installation."""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import threading
import urllib.request
import uuid
import zlib

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(r"E:\Github\Building-Generation-Validation\.runtime")
sys.path.insert(0, str(ROOT))

from researchops import desktop_bundle
from researchops.dashboard_state import process_identity

SCOPES = {"fixture": "FIXTURE_LAYOUT_ONLY", "installed": "INSTALLED_NATIVE_SERVICE"}
PANELS = {"mission", "gpu", "codex", "claude"}
CRITICAL = {"connection", "refresh", "runtime", "gpuState", "gpuUtil", "codexState",
            "claudeState", "observed", "gpuObserved", "composerPrompt", "composerSubmit"}
SHA = re.compile(r"[0-9a-f]{64}\Z")
BIRTH = re.compile(r"[0-9]{10,24}\Z")


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def parse_size(value):
    match = re.fullmatch(r"([0-9]{3,4})x([0-9]{3,4})", value)
    if not match:
        raise argparse.ArgumentTypeError("Expected WxH")
    width, height = map(int, match.groups())
    if not 800 <= width <= 2560 or not 600 <= height <= 1600:
        raise argparse.ArgumentTypeError("Size must be 800..2560 by 600..1600")
    return width, height


def parse_seconds(value):
    try:
        result = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Seconds must be 10..60") from error
    if not 10 <= result <= 60:
        raise argparse.ArgumentTypeError("Seconds must be 10..60")
    return result


def allowed_app(value):
    path = desktop_bundle.safe_path(Path(value).absolute()).resolve(strict=True)
    roots = [desktop_bundle.safe_path(RUNTIME / "desktop" / name).resolve()
             for name in ("candidates", "snapshots")]
    if (path.name.casefold() != "scenecontrol.exe" or not path.is_file()
            or not any(path.is_relative_to(root) for root in roots)):
        raise ValueError("APP_OUTSIDE_OWNED_DESKTOP_DIRECTORY")
    with path.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise ValueError("APP_NOT_WINDOWS_EXECUTABLE")
    return path


def source_evidence():
    missing = [name for name in desktop_bundle.SOURCE_FILES if not (ROOT / name).is_file()]
    if missing:
        return {"status": "INCOMPLETE", "sha256": None, "missing": missing}
    try:
        manifest = desktop_bundle.source_manifest(ROOT)
        return {"status": "COMPLETE", "sha256": manifest["sha256"], "files": manifest["files"]}
    except (OSError, ValueError):
        return {"status": "UNVERIFIED", "sha256": None, "reason": "SOURCE_MANIFEST_UNAVAILABLE"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def fixture_state():
    """One cache GET only. No StatusCache, SQLite reader, SSH, or model invocation."""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        request = urllib.request.Request("http://127.0.0.1:8765/api/status",
                                         headers={"Accept": "application/json"})
        with opener.open(request, timeout=4) as response:
            body = response.read(1024 * 1024 + 1)
            if response.status != 200 or len(body) > 1024 * 1024:
                raise ValueError("INVALID_SAFE_STATUS")
        def reject_constant(value):
            raise ValueError("NONFINITE_STATUS")
        state = json.loads(body, parse_constant=reject_constant)
        if not isinstance(state, dict) or state.get("schema") != 1 or state.get("read_only") is not True:
            raise ValueError("INVALID_SAFE_STATUS")
        return state, {"source": "REAL_READ_ONLY_CACHE", "read_attempts": 1,
                       "observed_at": state.get("observed_at"), "frozen_copy": True}
    except (OSError, ValueError, UnicodeError):
        now = utc()
        state = {"schema": 1, "read_only": True, "observed_at": now,
                 "reason": "FIXTURE_SYNTHETIC_FALLBACK",
                 "controller": {"paused": "UNKNOWN", "task_counts": {},
                                "daily_reviews": {"day": now[:10], "used": None,
                                                  "limit": None, "remaining": None}},
                 "engines": {key: {"state": "UNKNOWN", "active_attempts": [], "last_attempt": {}}
                             for key in ("codex", "claude")},
                 "mission": {"tasks": [], "active_task_ids": []},
                 "research_observer": {"transport": "FIXTURE_SYNTHETIC", "stale": True,
                                       "observed_at": now, "progress_signals": []},
                 "gpu": {"status": "UNAVAILABLE", "observed_at": None,
                         "last_checked_at": now, "gpus": [], "processes": [],
                         "reason": "FIXTURE_SYNTHETIC_FALLBACK"}}
        return state, {"source": "SYNTHETIC_FALLBACK", "read_attempts": 1,
                       "reason": "LIVE_SAFE_CACHE_UNAVAILABLE", "frozen_copy": True}


class FrozenCache:
    def __init__(self, state):
        self.state = copy.deepcopy(state)

    def snapshot(self):
        return copy.deepcopy(self.state)


def fixture_server():
    from researchops.dashboard_server import LocalServer, resources
    state, provenance = fixture_state()
    assets = resources(desktop_bundle.safe_path(RUNTIME / "dashboard" / "assets"))
    server = LocalServer(("127.0.0.1", 18766), FrozenCache(state), assets)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1},
                              name="OwnedNativeFixture", daemon=True)
    try:
        thread.start()
    except BaseException:
        server.server_close()
        raise
    provenance["resource_sha256"] = {name: hashlib.sha256(body).hexdigest()
                                     for name, (_, body) in assets.items()}
    return server, thread, provenance


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def visible_rect(element, width, height):
    if not isinstance(element, dict) or element.get("visible") is not True or element.get("insideViewport") is not True:
        return False
    if element.get("found", True) is not True:
        return False
    rect = element.get("rect", element)
    if not isinstance(rect, dict):
        return False
    if not all(finite(rect.get(key)) for key in ("x", "y", "width", "height", "right", "bottom")):
        return False
    return (rect["width"] > 0 and rect["height"] > 0 and rect["x"] >= -0.01 and rect["y"] >= -0.01
            and rect["right"] <= width + 0.01 and rect["bottom"] <= height + 0.01
            and abs(rect["x"] + rect["width"] - rect["right"]) <= 0.1
            and abs(rect["y"] + rect["height"] - rect["bottom"]) <= 0.1)


def png_evidence(path):
    """Validate PNG framing/CRCs and compressed image data, not merely its extension."""
    path = desktop_bundle.safe_path(path)
    if not path.is_file() or not 45 <= path.stat().st_size <= 64 * 1024 * 1024:
        raise ValueError("PNG_MISSING_OR_INVALID_SIZE")
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("PNG_SIGNATURE_INVALID")
    offset, width, height, compressed, ended = 8, None, None, bytearray(), False
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        end = offset + 12 + length
        if end > len(data):
            raise ValueError("PNG_TRUNCATED")
        body = data[offset + 8:offset + 8 + length]
        crc = struct.unpack(">I", data[offset + 8 + length:end])[0]
        if zlib.crc32(kind + body) & 0xffffffff != crc:
            raise ValueError("PNG_CRC_INVALID")
        if width is None:
            if kind != b"IHDR" or length != 13:
                raise ValueError("PNG_HEADER_INVALID")
            width, height = struct.unpack(">II", body[:8])
            if not 32 <= width <= 8192 or not 32 <= height <= 8192:
                raise ValueError("PNG_DIMENSIONS_INVALID")
        if kind == b"IDAT":
            compressed.extend(body)
        offset = end
        if kind == b"IEND":
            if length != 0 or offset != len(data):
                raise ValueError("PNG_END_INVALID")
            ended = True
            break
    decoder = zlib.decompressobj()
    decoded = decoder.decompress(bytes(compressed), 96 * 1024 * 1024 + 1)
    if not ended or not compressed or not decoder.eof or decoder.unused_data or len(decoded) > 96 * 1024 * 1024:
        raise ValueError("PNG_IMAGE_DATA_INVALID")
    return {"path": str(path), "width": width, "height": height,
            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def avatar_geometry_valid(avatars):
    if not isinstance(avatars, dict) or set(avatars) != {"david", "lucy"}:
        return False
    for key, item in avatars.items():
        if not isinstance(item, dict):
            return False
        values = [item.get(name) for name in ("naturalWidth", "naturalHeight", "frameContentWidth",
                  "frameContentHeight", "imageContentWidth", "imageContentHeight")]
        if not all(finite(value) and value > 0 for value in values):
            return False
        nw, nh, fw, fh, iw, ih = values
        actual = item.get("image")
        if (not isinstance(actual, dict) or not all(finite(actual.get(k)) and actual[k] > 0 for k in ("width", "height"))
                or abs(actual["width"] / actual["height"] - nw / nh) > .02):
            return False
        if (item.get("loaded") is not True or item.get("gridColumns") != 3 or item.get("gridRows") != 2
                or item.get("src") != "/assets/" + key + ".jpg" or item.get("objectFit") != "contain"
                or item.get("overflowX") not in ("hidden", "clip") or item.get("overflowY") not in ("hidden", "clip")
                or abs(fw / fh - (nw / 3) / (nh / 2)) > .02 or abs(iw / ih - nw / nh) > .02
                or abs(iw / 3 - fw) > 1 or abs(ih / 2 - fh) > 1):
            return False
    return True


def avatar_videos_valid(avatars):
    """Reject stretched, unequal, remote, unloaded or audible video portraits."""
    if not avatar_geometry_valid(avatars):
        return False
    sizes = []
    for name, avatar in avatars.items():
        v = avatar.get("video")
        if not isinstance(v, dict): return False
        if (v.get("src") != "/assets/" + name + ".mp4" or v.get("readyState", 0) < 2
                or v.get("muted") is not True or v.get("loop") is not True
                or v.get("error") is not None or v.get("objectFit") != "contain"
                or v.get("opacity") != 1 or v.get("playbackRate") != 1):
            return False
        rect = v.get("rect", {})
        values = [v.get("width"), v.get("height"), rect.get("width"), rect.get("height")]
        if not all(finite(n) and n > 0 for n in values): return False
        nw, nh, width, height = values
        if (abs(nw / nh - 1) > .01 or abs(width / height - 1) > .02
                or abs(width - avatar["frameContentWidth"]) > 1
                or abs(height - avatar["frameContentHeight"]) > 1): return False
        sizes.append((width, height))
    return all(abs(a - b) <= 1 for a, b in zip(*sizes))


def inspect_native(record, args, run_id, app, pid, birth, png):
    r = record if isinstance(record, dict) else {}
    viewport = r.get("viewport") if isinstance(r.get("viewport"), dict) else {}
    width, height, dpr = (viewport.get(key) for key in ("width", "height", "dpr"))
    viewport_ok = all(finite(value) and value > 0 for value in (width, height, dpr))
    panels = r.get("panels") if isinstance(r.get("panels"), dict) else {}
    critical = r.get("critical_elements") if isinstance(r.get("critical_elements"), dict) else {}
    scroll, client = r.get("document_scroll_height"), r.get("document_client_height")
    package = r.get("bundle_sha256") or r.get("package_sha256")
    checks = {
        "native_schema": type(r.get("schema")) is int and r.get("schema") == 1,
        "native_owner": r.get("owner") == desktop_bundle.OWNER,
        "run_id_bound": r.get("run_id") == run_id and r.get("verification_id") == run_id,
        "scope_exact": r.get("scope") == SCOPES[args.mode],
        "native_success": r.get("success") is True,
        "capture_completed": r.get("captured") is True,
        "own_child_pid": type(r.get("pid")) is int and r.get("pid") == pid,
        "own_child_birth": bool(isinstance(birth, str) and BIRTH.fullmatch(birth)) and r.get("process_birth") == birth,
        "app_path_bound": isinstance(r.get("app_path"), str) and os.path.normcase(r.get("app_path", "")) == os.path.normcase(str(app)),
        "native_window": str(r.get("native_window_handle", "")).isdigit() and int(r.get("native_window_handle", "0")) > 0 and r.get("title") == "SCENE // CONTROL",
        "native_dimensions": all(finite(r.get(k)) and r[k] > 0 for k in ("client_width", "client_height", "dpi")),
        "viewport_observed": viewport_ok,
        "four_panels_visible_inside": viewport_ok and set(panels) == PANELS and all(visible_rect(panels[key], width, height) for key in PANELS),
        "all_critical_visible_inside": viewport_ok and set(critical) == CRITICAL and all(visible_rect(critical[key], width, height) for key in CRITICAL),
        "no_document_vertical_scroll": finite(scroll) and finite(client) and client > 0 and scroll <= client,
        "png_valid": bool(png),
        "png_matches_viewport": bool(png) and viewport_ok and abs(png["width"] - width * dpr) <= 2.5 and abs(png["height"] - height * dpr) <= 2.5,
        "uk_time_label": bool(re.search(r"UK / (?:BST|GMT)", str(r.get("time_text", "")))),
        "no_model_calls": type(r.get("model_calls")) is int and r.get("model_calls") == 0,
        "fixed_url": r.get("url") == ("http://127.0.0.1:18766" if args.mode == "fixture" else "http://127.0.0.1:8765"),
    }
    layout = r.get("layout") if isinstance(r.get("layout"), dict) else {}
    checks["avatar_proportions_correct"] = (layout.get("checks", {}).get("avatarProportionsCorrect") is True
                                              and avatar_geometry_valid(layout.get("avatars")))
    checks["avatar_video_layout_correct"] = avatar_videos_valid(layout.get("avatars"))
    motion = layout.get("avatarMotion", {})
    checks["avatar_videos_actually_animate_and_pause"] = (set(motion) == {"david", "lucy"}
        and all(isinstance(v, dict) and v.get("advanced") is True and v.get("pausedHeld") is True
                and v.get("resumed") is True for v in motion.values()))
    native_checks = r.get("native_checks") if isinstance(r.get("native_checks"), dict) else {}
    checks["native_capture_stable"] = (set(native_checks) == {"visible_normal_before_probe",
        "visible_normal_before_capture", "visible_normal_after_capture", "geometry_stable_during_probe",
        "geometry_stable_during_capture"} and all(value is True for value in native_checks.values()))
    checks["native_visible_not_minimized"] = (r.get("window_visible") is True
        and r.get("window_normal") is True and r.get("window_minimized") is False)
    document = layout.get("document") if isinstance(layout.get("document"), dict) else {}
    sw, cw = document.get("width"), document.get("clientWidth")
    checks["no_document_horizontal_scroll"] = finite(sw) and finite(cw) and cw > 0 and sw <= cw
    if args.mode == "fixture":
        checks["fixture_did_not_ensure"] = r.get("ensure_calls") == 0 and r.get("scheduled_task_operations") == 0
    else:
        checks["installed_bundle_bound"] = bool(isinstance(package, str) and SHA.fullmatch(package)) and app.parent.name == "app" and app.parent.parent.name == package
        checks["installed_source_bound"] = bool(isinstance(r.get("source_sha256"), str) and SHA.fullmatch(r["source_sha256"]))
        checks["installed_verified_ensure"] = type(r.get("ensure_calls")) is int and r["ensure_calls"] >= 1
    return checks


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True)
    parser.add_argument("--mode", choices=SCOPES, required=True)
    parser.add_argument("--size", type=parse_size, default=(1280, 800))
    parser.add_argument("--seconds", type=parse_seconds, default=15)
    args = parser.parse_args(argv)
    run_id = str(uuid.uuid4())
    directory = desktop_bundle.safe_path(RUNTIME / "desktop" / "verification" / run_id)
    directory.mkdir(parents=True, exist_ok=False)
    report = {"schema": 1, "run_id": run_id, "scope": SCOPES[args.mode], "mode": args.mode,
              "observed_at": utc(), "requested_size": list(args.size), "seconds": args.seconds,
              "success": False, "checks": {}, "native": None, "evidence": str(directory),
              "termination_attempted": False, "fixture": None, "app": str(args.app),
              "app_sha256": None, "source_sha256": None}
    server = thread = child = None
    try:
        report["source"] = source_evidence()
        report["source_sha256"] = report["source"].get("sha256")
        report["source_hash_scope"] = "CURRENT_WORKTREE_SOURCE_FILES"
        app = allowed_app(args.app)
        report.update(app=str(app), app_sha256=digest(app))
        if args.mode == "fixture":
            server, thread, report["fixture"] = fixture_server()
        command = [str(app), "--smoke" if args.mode == "fixture" else "--verify", run_id,
                   "--size", f"{args.size[0]}x{args.size[1]}", "--seconds", str(args.seconds)]
        if args.mode == "fixture":
            command += ["--url", "http://127.0.0.1:18766"]
        with (directory / "native-stdout.log").open("xb") as stdout, (directory / "native-stderr.log").open("xb") as stderr:
            child = subprocess.Popen(command, cwd=app.parent, stdin=subprocess.DEVNULL,
                                     stdout=stdout, stderr=stderr)
            birth = process_identity(child.pid)
            report.update(child_pid=child.pid, child_birth=birth)
            try:
                report["exit_code"] = child.wait(timeout=args.seconds + 35)
                report["timed_out"] = False
            except subprocess.TimeoutExpired:
                report.update(exit_code=None, timed_out=True, reason="OWN_NATIVE_CHILD_DID_NOT_EXIT")
                # Do not terminate an unverified/reused PID or any existing app/service.
                # The owned native diagnostic timer is responsible for normal closure.
                report["own_child_still_running"] = child.poll() is None
        native_path = desktop_bundle.safe_path(directory / "native.json")
        try:
            native = desktop_bundle.read_small_json(native_path)
        except (OSError, ValueError):
            native = None
        report["native"] = native
        try:
            png = png_evidence(directory / "content.png")
        except (OSError, ValueError, zlib.error):
            png = None
        report["png"] = png
        checks = inspect_native(native, args, run_id, app, child.pid, birth, png)
        checks["run_exit_zero"] = report["exit_code"] == 0 and report["timed_out"] is False
        checks["app_unchanged"] = digest(app) == report["app_sha256"]
        report["source_after"] = source_evidence()
        if report["source"]["status"] == "COMPLETE":
            checks["source_unchanged_during_run"] = report["source_after"].get("sha256") == report["source_sha256"]
        report["checks"] = checks
    except Exception as error:
        report.update(reason="NATIVE_VERIFICATION_EXCEPTION", error_type=type(error).__name__)
        report["checks"]["verification_completed"] = False
    finally:
        if server is not None:
            try:
                if thread is not None and thread.is_alive():
                    server.shutdown()
                server.server_close()
                if thread is not None:
                    thread.join(timeout=5)
                report["checks"]["own_fixture_thread_closed"] = thread is None or not thread.is_alive()
            except Exception:
                report["checks"]["own_fixture_thread_closed"] = False
        report["completed_at"] = utc()
        report["success"] = bool(report["checks"]) and all(value is True for value in report["checks"].values())
        target = desktop_bundle.safe_path(directory / "NATIVE-VERIFICATION.json")
        with target.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
    print(json.dumps({"success": report["success"], "scope": report["scope"], "run_id": run_id,
                      "failed": [key for key, value in report["checks"].items() if value is not True],
                      "fixture_source": (report.get("fixture") or {}).get("source"),
                      "evidence": str(directory), "report": str(target)}, ensure_ascii=False))
    return 0 if report["success"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

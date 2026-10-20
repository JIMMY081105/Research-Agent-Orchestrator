"""Independent immutable UI bundles. The active controller snapshot is never changed."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import shutil

OWNER = "BGV.Windows.ResearchOps.UI.v1"
FILES = (
    "dashboard.py", "researchops/__init__.py", "researchops/dashboard_server.py",
    "researchops/dashboard_state.py", "researchops/dashboard_gpu.py", "researchops/dashboard_web.py",
    "researchops/dashboard_bundle.py", "config/dashboard.example.json", "tools/dashboard.ps1",
    "tools/review_dashboard.py", "tools/verify_dashboard.py", "tools/test_dashboard.py",
    "DASHBOARD.md", "README.md", "POLICY.md", "AVATARS.md",
    "tests/test_dashboard_state.py",
    "tests/test_dashboard_gpu.py", "tests/test_dashboard_server.py", "tests/test_dashboard_bundle.py",
    "researchops/dashboard_tasks.py", "tests/test_dashboard_tasks.py",
    "researchops/worker_store.py", "researchops/worker_web.py", "tests/test_worker_store.py",
    "tests/test_worker_http.py", "tests/test_dashboard_avatar_media.py",
)
AVATARS = {
    "david.jpg": "d86833586e9e0c6b9ac84e873266386c011edc48743d2d9b14d6f22eee08a253",
    "lucy.jpg": "c14b2e3c278c6961b72c5200ba0ace9749cc9ae49d882fa4e112d4eb52799f5e",
}
AVATAR_VIDEOS = {
    "david.mp4": "421aa392c0b556ef3ec799322d40e9f1864592bc8820d154880ade238dd4afc0",
    "lucy.mp4": "177972242f35d13fd931a4be4beae86a8d8095d37c7e2677968e65b09a76d73a",
}


def video_assets(directory):
    """Only the two approved local, content-bound, silent avatar clips."""
    values = {}
    for name, expected in AVATAR_VIDEOS.items():
        path = safe_path(Path(directory) / name)
        if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("UNAPPROVED_AVATAR_VIDEO")
        data = path.read_bytes()
        if len(data) < 16 or data[4:8] != b"ftyp" or digest(data) != expected:
            raise ValueError("UNAPPROVED_AVATAR_VIDEO")
        values[name] = data
    return values


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_path(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError("UI_REPARSE_PATH")
    return path


def validate_config(value):
    expected = {"owner", "bind", "port", "ssh", "ssh_alias", "state_poll_seconds",
                "gpu_poll_seconds", "gpu_stale_seconds"}
    if (type(value) is not dict or set(value) != expected or value["owner"] != OWNER
            or value["bind"] != "127.0.0.1" or type(value["port"]) is not int
            or not 1024 <= value["port"] <= 65535
            or value["state_poll_seconds"] != 2 or value["gpu_poll_seconds"] != 30
            or value["gpu_stale_seconds"] != 90
            or type(value["ssh_alias"]) is not str
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", value["ssh_alias"])
            or type(value["ssh"]) is not str or not Path(value["ssh"]).is_absolute()
            or Path(value["ssh"]).name.lower() != "ssh.exe"):
        raise ValueError("INVALID_UI_CONFIG")
    safe_path(value["ssh"])
    return value


def source_manifest(root):
    root = safe_path(root)
    values = {}
    for name in FILES:
        path = safe_path(root / name)
        if not path.is_file() or path.stat().st_size > 1024 * 1024:
            raise ValueError("UI_SOURCE_MISSING_OR_TOO_LARGE")
        values[name] = digest(path.read_bytes())
    return {"files": values, "sha256": digest(canonical(values))}


def bundle_manifest(root, config, assets):
    source = source_manifest(root)
    files = dict(source["files"])
    files["config/live.json"] = digest(canonical(validate_config(config)))
    for name, expected in AVATARS.items():
        value = safe_path(Path(assets) / name).read_bytes()
        if len(value) > 1024 * 1024 or not value.startswith(b"\xff\xd8\xff") or digest(value) != expected:
            raise ValueError("UNAPPROVED_AVATAR_ASSET")
        files["assets/" + name] = expected
    files.update({"assets/" + name: digest(data) for name, data in video_assets(assets).items()})
    return {"owner": OWNER, "source_sha256": source["sha256"], "files": files,
            "sha256": digest(canonical(files))}


def read_small_json(path):
    path = safe_path(path)
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("UI_METADATA_TOO_LARGE")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def verify(bundle, expected):
    bundle = safe_path(bundle)
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("UI_HASH_REQUIRED")
    record = read_small_json(bundle / "manifest.json")
    files = record.get("files")
    allowed = set(FILES) | {"config/live.json", *["assets/" + name for name in (*AVATARS, *AVATAR_VIDEOS)]}
    if (record.get("owner") != OWNER or type(files) is not dict or set(files) != allowed
            or record.get("sha256") != expected or digest(canonical(files)) != expected):
        raise ValueError("UI_MANIFEST_INVALID")
    if any(files["assets/" + name] != expected_sha for name, expected_sha in AVATARS.items()):
        raise ValueError("UNAPPROVED_AVATAR_ASSET")
    if any(files["assets/" + name] != expected_sha for name, expected_sha in AVATAR_VIDEOS.items()):
        raise ValueError("UNAPPROVED_AVATAR_VIDEO")
    source = bundle / "source"
    found = set()
    for path in source.rglob("*"):
        safe_path(path)
        if path.is_file():
            rel = path.relative_to(source).as_posix()
            if rel.endswith((".pyc", ".pyo")) and "__pycache__" in path.parts:
                continue
            found.add(rel)
    if found != allowed:
        raise ValueError("UI_SNAPSHOT_FILESET_CHANGED")
    for rel, sha in files.items():
        path = safe_path(source / rel)
        if path.stat().st_size > 2 * 1024 * 1024 or digest(path.read_bytes()) != sha:
            raise ValueError("UI_SNAPSHOT_CONTENT_CHANGED")
    source_files = {name: files[name] for name in FILES}
    if record.get("source_sha256") != digest(canonical(source_files)):
        raise ValueError("UI_SOURCE_BINDING_CHANGED")
    validate_config(read_small_json(source / "config/live.json"))
    return record


def freeze(root, runtime, config, assets, test_path, review_path):
    root, runtime = safe_path(root), safe_path(runtime)
    record = bundle_manifest(root, config, assets)
    tests, review = read_small_json(test_path), read_small_json(review_path)
    if (tests.get("source_sha256") != record["source_sha256"] or tests.get("success") is not True
            or tests.get("failures") or tests.get("errors") or tests.get("skipped")
            or tests.get("discovered") != tests.get("tests_run") or tests.get("tests_run", 0) < 40):
        raise ValueError("CURRENT_UI_TESTS_REQUIRED")
    if (review.get("source_sha256") != record["source_sha256"] or review.get("verdict") != "PASS"
            or review.get("bundle_sha256") != record["sha256"]
            or review.get("issues") != [] or review.get("tools_disabled") is not True
            or not review.get("call_id") or not review.get("session_id")
            or review.get("tests_sha256") != digest(Path(test_path).read_bytes())):
        raise ValueError("CURRENT_INDEPENDENT_UI_REVIEW_REQUIRED")
    target = runtime / "dashboard" / "snapshots" / record["sha256"]
    safe_path(target)
    if target.exists():
        verify(target, record["sha256"])
        return record, target
    target.mkdir(parents=True)
    source = target / "source"
    for name in FILES:
        destination = source / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, destination)
    (source / "config/live.json").write_bytes(canonical(config))
    (source / "assets").mkdir()
    for name in (*AVATARS, *AVATAR_VIDEOS):
        shutil.copyfile(Path(assets) / name, source / "assets" / name)
    (target / "manifest.json").write_bytes(canonical(record))
    verify(target, record["sha256"])
    return record, target

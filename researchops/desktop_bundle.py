"""Independent, content-addressed desktop snapshots; never modifies the UI/core."""
from __future__ import annotations

from pathlib import Path, PurePosixPath
import re
import shutil

from . import dashboard_bundle


OWNER = "BGV.Windows.SceneControl.Desktop.v1"
SOURCE_FILES = dashboard_bundle.FILES + (
    "desktop.py", "researchops/desktop_bundle.py", "researchops/desktop_recovery.py",
    "tools/desktop.ps1", "tools/build_desktop.py", "tools/review_desktop.py",
    "tools/test_desktop.py", "tools/verify_desktop.py", "native/SceneControl.cs",
    "native/SceneControl.manifest", "native/DesktopFiles.cs", "native/SceneControlLauncher.cs",
    "config/desktop-dependencies.json", "DESKTOP.md",
    "tests/test_desktop_bundle.py", "tests/test_desktop_recovery.py",
    "tests/test_desktop_native.py", "tests/test_desktop_environment.py", "tests/test_desktop_install.py", "tests/test_desktop_launcher.py", "tests/test_desktop_review.py",
    "worker.py", "researchops/worker_rpc.py", "researchops/worker_service.py", "researchops/worker_review.py",
    "researchops/winproc.py", "tools/worker.ps1", "config/worker-AGENTS.md", "WORKER.md",
    "tests/test_worker_rpc.py", "tests/test_worker_service.py",
)
APP_FILES = (
    "SceneControl.exe", "Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll",
    "WebView2Loader.dll", "SceneControl.ico", "SceneControlLauncher.exe",
)
DEPENDENCY_FILES = frozenset(APP_FILES[1:4])
BUILD_INPUTS = (
    "native/SceneControl.cs", "native/SceneControl.manifest", "native/DesktopFiles.cs",
    "native/SceneControlLauncher.cs", "tools/build_desktop.py",
    "config/desktop-dependencies.json",
)
canonical = dashboard_bundle.canonical
digest = dashboard_bundle.digest
safe_path = dashboard_bundle.safe_path
read_small_json = dashboard_bundle.read_small_json
validate_config = dashboard_bundle.validate_config
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _relative(name):
    if (type(name) is not str or not name or "\\" in name or ":" in name
            or PurePosixPath(name).is_absolute() or any(p in (".", "..", "") for p in name.split("/"))):
        raise ValueError("DESKTOP_UNSAFE_RELATIVE_PATH")
    return name


def _sources():
    if len(set(SOURCE_FILES)) != len(SOURCE_FILES):
        raise ValueError("DESKTOP_DUPLICATE_SOURCE_PATH")
    for name in SOURCE_FILES:
        _relative(name)
    return SOURCE_FILES


def _bytes(path, limit):
    path = safe_path(path)
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError("DESKTOP_FILE_MISSING_OR_TOO_LARGE")
    data = path.read_bytes()
    if len(data) > limit:
        raise ValueError("DESKTOP_FILE_MISSING_OR_TOO_LARGE")
    return data


def _hashmap(value, names):
    return (type(value) is dict and set(value) == set(names)
            and all(type(sha) is str and _SHA.fullmatch(sha) for sha in value.values()))


def source_manifest(root):
    root = safe_path(root)
    files = {name: digest(_bytes(root / name, 2 * 1024 * 1024)) for name in _sources()}
    return {"files": files, "sha256": digest(canonical(files))}


def _dependencies(value):
    if (type(value) is not dict or set(value) != {"package", "version", "url", "sha256", "files"}
            or value.get("package") != "Microsoft.Web.WebView2"
            or type(value.get("version")) is not str or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){2,3}", value["version"])
            or type(value.get("url")) is not str or not value["url"].startswith("https://")
            or len(value["url"]) > 2048 or any(c.isspace() for c in value["url"])
            or type(value.get("sha256")) is not str or not _SHA.fullmatch(value["sha256"])
            or not _hashmap(value.get("files"), DEPENDENCY_FILES)):
        raise ValueError("DESKTOP_DEPENDENCIES_INVALID")
    return value


def _build(value, sources, app_files, dependencies):
    if (type(value) is not dict or value.get("success") is not True
            or not _hashmap(value.get("source_inputs"), BUILD_INPUTS)
            or value["source_inputs"] != {name: sources[name] for name in BUILD_INPUTS}
            or not _hashmap(value.get("app_files"), APP_FILES) or value["app_files"] != app_files):
        raise ValueError("DESKTOP_BUILD_BINDING_INVALID")
    compiler = value.get("compiler")
    if (type(compiler) is not dict or set(compiler) != {"path", "sha256", "version"}
            or type(compiler.get("path")) is not str or not Path(compiler["path"]).is_absolute()
            or Path(compiler["path"]).name.lower() != "csc.exe"
            or type(compiler.get("sha256")) is not str or not _SHA.fullmatch(compiler["sha256"])
            or type(compiler.get("version")) is not str or not 1 <= len(compiler["version"]) <= 512
            or any(ord(c) < 32 and c not in "\r\n\t" for c in compiler["version"])):
        raise ValueError("DESKTOP_COMPILER_EVIDENCE_INVALID")
    for name in DEPENDENCY_FILES:
        if app_files[name] != dependencies["files"][name]:
            raise ValueError("DESKTOP_DEPENDENCY_HASH_MISMATCH")
    return value


def _avatars(assets):
    values = {}
    for name, expected in dashboard_bundle.AVATARS.items():
        _relative(name)
        data = _bytes(Path(assets) / name, 1024 * 1024)
        if not data.startswith(b"\xff\xd8\xff") or digest(data) != expected:
            raise ValueError("UNAPPROVED_AVATAR_ASSET")
        values[name] = expected
    values.update({name: digest(data) for name, data in dashboard_bundle.video_assets(assets).items()})
    return values


def _app(app):
    return {name: digest(_bytes(Path(app) / name, 64 * 1024 * 1024)) for name in APP_FILES}


def bundle_manifest(root, config, assets, app, build_path):
    source = source_manifest(root)
    app_files = _app(safe_path(app))
    dependencies = _dependencies(read_small_json(Path(root) / "config/desktop-dependencies.json"))
    _build(read_small_json(build_path), source["files"], app_files, dependencies)
    files = {"source/" + name: sha for name, sha in source["files"].items()}
    files["source/config/live.json"] = digest(canonical(validate_config(config)))
    files.update({"source/assets/" + name: sha for name, sha in _avatars(assets).items()})
    files.update({"app/" + name: sha for name, sha in app_files.items()})
    files["build.json"] = digest(_bytes(build_path, 2 * 1024 * 1024))
    return {"owner": OWNER, "source_sha256": source["sha256"], "files": files,
            "sha256": digest(canonical(files))}


def _inventory(directory, allowed):
    allowed_dirs = set()
    for name in allowed:
        allowed_dirs.update(str(parent) for parent in PurePosixPath(name).parents if str(parent) != ".")
    found = set()
    stack = [directory]
    while stack:
        for entry in stack.pop().iterdir():
            entry = safe_path(entry)  # Reject links/junctions before ever descending.
            rel = entry.relative_to(directory).as_posix()
            if entry.is_dir():
                if rel not in allowed_dirs:
                    raise ValueError("DESKTOP_SNAPSHOT_FILESET_CHANGED")
                stack.append(entry)
            elif entry.is_file():
                found.add(rel)
            else:
                raise ValueError("DESKTOP_SNAPSHOT_FILESET_CHANGED")
    if found != allowed:
        raise ValueError("DESKTOP_SNAPSHOT_FILESET_CHANGED")


def verify(bundle, expected):
    bundle = safe_path(bundle)
    if type(expected) is not str or not _SHA.fullmatch(expected):
        raise ValueError("DESKTOP_HASH_REQUIRED")
    record = read_small_json(bundle / "manifest.json")
    allowed = {"source/" + name for name in _sources()} | {"source/config/live.json", "build.json"}
    allowed.update("source/assets/" + name for name in (*dashboard_bundle.AVATARS, *dashboard_bundle.AVATAR_VIDEOS))
    allowed.update("app/" + name for name in APP_FILES)
    if (type(record) is not dict or set(record) != {"owner", "source_sha256", "files", "sha256"}
            or record.get("owner") != OWNER or not _hashmap(record.get("files"), allowed)
            or record.get("sha256") != expected or digest(canonical(record["files"])) != expected):
        raise ValueError("DESKTOP_MANIFEST_INVALID")
    _inventory(bundle, allowed | {"manifest.json"})
    files = record["files"]
    for name, sha in files.items():
        limit = 64 * 1024 * 1024 if name.startswith("app/") else 2 * 1024 * 1024
        if digest(_bytes(bundle / name, limit)) != sha:
            raise ValueError("DESKTOP_SNAPSHOT_CONTENT_CHANGED")
    sources = {name: files["source/" + name] for name in _sources()}
    if record.get("source_sha256") != digest(canonical(sources)):
        raise ValueError("DESKTOP_SOURCE_BINDING_CHANGED")
    validate_config(read_small_json(bundle / "source/config/live.json"))
    _avatars(bundle / "source/assets")
    dependencies = _dependencies(read_small_json(bundle / "source/config/desktop-dependencies.json"))
    app_files = {name: files["app/" + name] for name in APP_FILES}
    _build(read_small_json(bundle / "build.json"), sources, app_files, dependencies)
    return record


def _gates(record, tests, review, tests_sha):
    if (type(tests) is not dict or tests.get("success") is not True
            or tests.get("source_unchanged") is not True
            or tests.get("source_sha256") != record["source_sha256"]
            or type(tests.get("tests_run")) is not int or tests["tests_run"] < 64
            or type(tests.get("discovered")) is not int or tests["discovered"] != tests["tests_run"]
            or any(tests.get(name) != [] for name in ("errors", "failures", "skipped"))):
        raise ValueError("CURRENT_DESKTOP_TESTS_REQUIRED")
    if (type(review) is not dict or review.get("owner") != OWNER
            or review.get("source_sha256") != record["source_sha256"]
            or review.get("bundle_sha256") != record["sha256"]
            or review.get("tests_sha256") != tests_sha or review.get("verdict") != "PASS"
            or review.get("issues") != [] or review.get("tools_disabled") is not True
            or any(type(review.get(name)) is not str or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", review[name])
                   for name in ("session_id", "call_id"))):
        raise ValueError("CURRENT_INDEPENDENT_DESKTOP_REVIEW_REQUIRED")


def freeze(root, runtime, config, assets, app, build_path, test_path, review_path):
    root, runtime = safe_path(root), safe_path(runtime)
    if runtime != root / ".runtime":
        raise ValueError("DESKTOP_RUNTIME_BOUNDARY_REQUIRED")
    record = bundle_manifest(root, config, assets, app, build_path)
    tests_bytes = _bytes(test_path, 2 * 1024 * 1024)
    tests, review = read_small_json(test_path), read_small_json(review_path)
    _gates(record, tests, review, digest(tests_bytes))
    home = safe_path(runtime / "desktop")
    target = safe_path(home / "snapshots" / record["sha256"])
    if target.exists():
        verify(target, record["sha256"])
        return record, target
    stage = safe_path(home / (".staging-" + record["sha256"]))
    home.mkdir(parents=True, exist_ok=True)
    if stage.exists():
        raise ValueError("DESKTOP_STAGING_EXISTS_RETAINED")
    stage.mkdir(exist_ok=False)
    for name in _sources():
        destination = safe_path(stage / "source" / name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(safe_path(root / name), destination)
    (stage / "source/config").mkdir(parents=True, exist_ok=True)
    (stage / "source/config/live.json").write_bytes(canonical(config))
    (stage / "source/assets").mkdir(parents=True, exist_ok=True)
    for name in (*dashboard_bundle.AVATARS, *dashboard_bundle.AVATAR_VIDEOS):
        shutil.copyfile(safe_path(Path(assets) / name), stage / "source/assets" / name)
    (stage / "app").mkdir()
    for name in APP_FILES:
        shutil.copyfile(safe_path(Path(app) / name), stage / "app" / name)
    shutil.copyfile(safe_path(build_path), stage / "build.json")
    (stage / "manifest.json").write_bytes(canonical(record))
    verify(stage, record["sha256"])
    # Recheck all source/build/config/asset/test/review evidence after copying.
    if (bundle_manifest(root, config, assets, app, build_path) != record
            or digest(_bytes(test_path, 2 * 1024 * 1024)) != digest(tests_bytes)
            or read_small_json(review_path) != review):
        raise ValueError("DESKTOP_INPUT_CHANGED_DURING_FREEZE")
    target.parent.mkdir(parents=True, exist_ok=True)
    safe_path(stage)
    safe_path(target)
    stage.rename(target)  # Atomic, same owned filesystem; never replaces a directory.
    verify(target, record["sha256"])
    return record, target

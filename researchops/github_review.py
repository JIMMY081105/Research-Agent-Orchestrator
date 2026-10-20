"""Explicit, immutable result delivery to one private repository, never a research runner."""
from __future__ import annotations
import base64
import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import uuid

OWNER = "BGV.Windows.GitHubReview.v1"
REPOSITORY = "JIMMY081105/Building-Generation-Validation"
ORIGIN = "https://github.com/" + REPOSITORY + ".git"
MAIN = Path(r"E:\Github\Building-Generation-Validation")
SOURCE_FILES = ("github_review.py", "researchops/__init__.py", "researchops/github_review.py",
                "tools/github.ps1", "tools/review_github.py", "config/github-review.example.json",
                "tests/test_github_review.py", "GITHUB.md", "POLICY.md", "README.md")
MAX_FILE = 8 * 1024 * 1024
MAX_TOTAL = 24 * 1024 * 1024
MAX_FILES = 16
HASH = re.compile(r"[0-9a-f]{64}\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
SECRET = re.compile(r"(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|github_pat_[A-Za-z0-9_]{20,}|"
                    r"gh[pousr]_[A-Za-z0-9]{20,}|sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}|"
                    r"(?i:bearer)\s+[A-Za-z0-9_.-]{20,}|"
                    r"(?i:api[_-]?key|access[_-]?token|password|secret)\s*[\"']?\s*[:=]\s*[\"'][^\"'\s]{12,}[\"'])")


class BridgeError(Exception):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def safe(path):
    p = Path(path).absolute()
    for part in (p, *p.parents):
        if part.is_symlink() or part.is_junction():
            raise BridgeError("REPARSE_PATH")
    return p


def read(path, limit=MAX_FILE):
    p = safe(path)
    with p.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise BridgeError("FILE_TOO_LARGE")
    return data


def object_json(data):
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise BridgeError("DUPLICATE_JSON_KEY")
            out[k] = v
        return out
    try:
        return json.loads(data.decode("utf-8-sig"), object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(BridgeError("INVALID_JSON_NUMBER")))
    except (ValueError, UnicodeError) as error:
        raise BridgeError("INVALID_JSON") from error


def load(path, limit=128 * 1024):
    return object_json(read(path, limit))


def save(path, value):
    p = safe(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    temporary = safe(p.parent / (p.name + "." + uuid.uuid4().hex + ".tmp"))
    with temporary.open("xb") as stream:
        stream.write(canonical(value) + b"\n")
    os.replace(temporary, p)


def task_id(value):
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError) as error:
        raise BridgeError("INVALID_TASK_ID") from error
    return value


def text(value, maximum):
    if (type(value) is not str or not value.strip() or len(value) > maximum
            or any(ord(c) < 32 and c not in "\n\t" for c in value) or SECRET.search(value)):
        raise BridgeError("INVALID_OR_SENSITIVE_TEXT")
    return value


def relative(value):
    if type(value) is not str or len(value) > 160 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]*", value):
        raise BridgeError("INVALID_ARTIFACT_PATH")
    parts = PurePosixPath(value).parts
    blocked = {".runtime", ".venv", ".git", "logs", "credentials", "secrets", "checkpoint", "checkpoints"}
    if (len(parts) > 4 or any(p in (".", "..") or p.lower() in blocked or p.endswith(".") for p in parts)
            or str(PurePosixPath(value)) != value or value.startswith("/")
            or PurePosixPath(value).suffix.lower() not in (".md", ".json", ".png", ".jpg", ".jpeg", ".webp")
            or any(re.search(r"(?i)(^|[_.-])(auth|token|secret|password|machine|raw|log)([_.-]|$)", p) for p in parts)
            or any(re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", p) for p in parts)):
        raise BridgeError("DISALLOWED_ARTIFACT_PATH")
    return value


def inspect_file(name, data):
    suffix = PurePosixPath(name).suffix.lower()
    if suffix in (".md", ".json"):
        if len(data) > 128 * 1024:
            raise BridgeError("REPORT_TEXT_TOO_LARGE")
        try:
            decoded = data.decode("utf-8")
        except UnicodeError as error:
            raise BridgeError("INVALID_UTF8_ARTIFACT") from error
        if SECRET.search(decoded) or "\x00" in decoded:
            raise BridgeError("SENSITIVE_ARTIFACT")
        if suffix == ".json":
            object_json(data)
    elif suffix == ".png":
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise BridgeError("INVALID_IMAGE_SIGNATURE")
    elif suffix in (".jpg", ".jpeg"):
        if not data.startswith(b"\xff\xd8\xff"):
            raise BridgeError("INVALID_IMAGE_SIGNATURE")
    elif not (data.startswith(b"RIFF") and data[8:12] == b"WEBP"):
        raise BridgeError("INVALID_IMAGE_SIGNATURE")
    # A signature check is a packaging check, never render/collision evidence.


def manifest(root):
    root = safe(root)
    files = {name: digest(read(root / name, 1024 * 1024)) for name in SOURCE_FILES}
    return {"files": files, "sha256": digest(canonical(files))}


@contextlib.contextmanager
def lock(runtime):
    runtime = safe(runtime)
    runtime.mkdir(parents=True, exist_ok=True)
    stream = safe(runtime / "bridge.lock").open("a+b")
    try:
        if stream.seek(0, 2) == 0:
            stream.write(b"0"); stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise BridgeError("BRIDGE_ALREADY_RUNNING") from error
        yield
    finally:
        stream.close()  # The OS releases the lock after a crash; no PID killing or lock deletion.


class Api:
    def __init__(self, gh=None):
        self.gh = str(safe(gh or shutil.which("gh") or r"C:\Program Files\GitHub CLI\gh.exe"))
        if not Path(self.gh).is_file():
            raise BridgeError("GITHUB_CLI_MISSING")

    def request(self, method, endpoint, payload=None, missing=False):
        prefix = "repos/" + REPOSITORY
        if method not in ("GET", "POST") or not (endpoint == "user" or endpoint == prefix or endpoint.startswith(prefix + "/")):
            raise BridgeError("ENDPOINT_NOT_ALLOWED")
        environment = dict(os.environ)
        for key in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN", "GH_HOST", "GH_REPO"):
            environment.pop(key, None)
        environment.update(GH_PROMPT_DISABLED="1", GH_PAGER="cat", NO_COLOR="1")
        args = [self.gh, "api", "--hostname", "github.com", "--method", method, endpoint]
        if payload is not None:
            args += ["--input", "-"]
        try:
            result = subprocess.run(args, input=canonical(payload) if payload is not None else None,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment,
                                    timeout=45, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired as error:
            raise BridgeError("GITHUB_TIMEOUT") from error
        except OSError as error:
            raise BridgeError("GITHUB_CLI_FAILED") from error
        if result.returncode:
            if missing and b"HTTP 404" in result.stderr:
                return None
            kind = "GITHUB_REQUEST_FAILED"
            for status, label in ((401, "AUTH"), (403, "PERMISSION_OR_RATE_LIMIT"), (404, "NOT_FOUND"),
                                  (409, "CONFLICT"), (422, "CONFLICT_OR_INVALID"), (429, "RATE_LIMIT")):
                if ("HTTP " + str(status)).encode() in result.stderr:
                    kind = "GITHUB_" + label
            raise BridgeError(kind)  # Never copy raw auth, network errors, or response bodies to logs.
        if len(result.stdout) > 4 * 1024 * 1024:
            raise BridgeError("GITHUB_RESPONSE_TOO_LARGE")
        return object_json(result.stdout)


def verify_repository(repo):
    repo = safe(repo)
    if repo != safe(MAIN):
        raise BridgeError("LOCAL_REPOSITORY_IDENTITY_MISMATCH")
    for arguments, expected in ((["rev-parse", "--show-toplevel"], str(repo).replace("\\", "/")),
                                (["remote", "get-url", "origin"], ORIGIN)):
        try:
            result = subprocess.run([shutil.which("git") or "git", "-C", str(repo), *arguments],
                                    capture_output=True, timeout=15,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired) as error:
            raise BridgeError("LOCAL_REPOSITORY_UNAVAILABLE") from error
        if result.returncode or result.stdout.decode("utf-8").strip() != expected:
            raise BridgeError("LOCAL_REPOSITORY_IDENTITY_MISMATCH")
    return repo


def passing_tests(path, source_sha):
    data = read(path, 1024 * 1024)
    tests = object_json(data)
    if (tests.get("success") is not True or tests.get("source_sha256") != source_sha
            or tests.get("source_unchanged") is not True or type(tests.get("tests_run")) is not int
            or tests["tests_run"] < 20 or tests.get("discovered") != tests["tests_run"]
            or tests.get("failures") != [] or tests.get("errors") != [] or tests.get("skipped") != []):
        raise BridgeError("COMPLETE_CURRENT_TESTS_REQUIRED")
    return digest(data)


def git_blob_sha(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


class Bridge:
    def __init__(self, repo=MAIN, runtime=None, root=None, api=None):
        self.repo = safe(repo)
        self.runtime = safe(runtime or self.repo / ".runtime/github")
        self.root = safe(root or Path(__file__).parents[1])
        self.api = api or Api()

    def connection(self):
        verify_repository(self.repo)
        metadata = self.api.request("GET", "repos/" + REPOSITORY)
        if (metadata.get("full_name") != REPOSITORY or metadata.get("private") is not True
                or metadata.get("archived") is not False or metadata.get("permissions", {}).get("push") is not True):
            raise BridgeError("PRIVATE_TARGET_OR_PERMISSION_MISMATCH")
        branch = metadata.get("default_branch")
        if type(branch) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,99}", branch) or ".." in branch:
            raise BridgeError("INVALID_DEFAULT_BRANCH")
        ref = self.api.request("GET", "repos/" + REPOSITORY + "/git/ref/heads/" + branch)
        sha = ref.get("object", {}).get("sha", "")
        if not SHA.fullmatch(sha) or ref.get("object", {}).get("type") != "commit":
            raise BridgeError("INVALID_BASE_REF")
        return {"state": "CONNECTED", "repository": REPOSITORY, "private": True, "base": branch,
                "base_commit": sha, "publication_tested": False, "automatic_merge": False, "observed_at": now()}

    def directory(self, ident, kind="outbox"):
        return safe(self.runtime / kind / task_id(ident))

    def prepare(self, ident):
        intake = self.directory(ident, "intake")
        request_data = read(intake / "ready.json", 64 * 1024)
        request = object_json(request_data)
        if (type(request) is not dict or set(request) != {"schema", "id", "title", "summary", "reported_status", "files"}
                or type(request["schema"]) is not int or request["schema"] != 1 or request["id"] != task_id(ident)
                or request["reported_status"] not in ("UNVERIFIED", "PARTIAL", "PASS", "FAIL")):
            raise BridgeError("INVALID_DELIVERY_REQUEST")
        text(request["title"], 120); text(request["summary"], 3000)
        if "\n" in request["title"] or not isinstance(request["files"], list) or not 1 <= len(request["files"]) <= MAX_FILES:
            raise BridgeError("INVALID_DELIVERY_FILES")
        items, contents, seen = [], {}, set()
        for item in request["files"]:
            if type(item) is not dict or set(item) != {"path", "sha256"} or not HASH.fullmatch(str(item["sha256"])):
                raise BridgeError("INVALID_DELIVERY_FILE")
            name = relative(item["path"])
            if name.lower() in seen or name.lower() in ("readme.md", "delivery-manifest.json"):
                raise BridgeError("DUPLICATE_OR_RESERVED_PATH")
            seen.add(name.lower())
            data = read(intake / name)
            if digest(data) != item["sha256"]:
                raise BridgeError("INPUT_HASH_MISMATCH")
            inspect_file(name, data)
            contents[name] = data
            items.append({"path": name, "sha256": digest(data), "bytes": len(data)})
        if sum(map(len, contents.values())) > MAX_TOTAL:
            raise BridgeError("DELIVERY_TOO_LARGE")
        connection = self.connection()
        commit = self.api.request("GET", "repos/" + REPOSITORY + "/git/commits/" + connection["base_commit"])
        tree = commit.get("tree", {}).get("sha", "")
        if not SHA.fullmatch(tree):
            raise BridgeError("INVALID_BASE_TREE")
        bundle = {"schema": 1, "owner": OWNER, "id": ident, "repository": REPOSITORY,
                  "branch": "bgv/review/" + ident, "prefix": "reviews/" + ident,
                  "base": connection["base"], "base_commit": connection["base_commit"], "base_tree": tree,
                  "title": request["title"], "summary": request["summary"], "reported_status": request["reported_status"],
                  "scientific_validation_by_bridge": "NOT_PERFORMED", "created_at": now(),
                  "request_sha256": digest(request_data), "source_sha256": manifest(self.root)["sha256"], "files": items}
        bundle["sha256"] = digest(canonical(bundle))
        folder = self.directory(ident)
        folder.mkdir(parents=True, exist_ok=False)
        for name, data in contents.items():
            destination = safe(folder / "files" / name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write(data)
        save(folder / "package.json", bundle)
        (folder / "PREVIEW.md").write_text(self.report(bundle), encoding="utf-8")
        save(folder / "state.json", {"state": "PREPARED_NOT_PUBLISHED", "id": ident, "updated_at": now()})
        return {"state": "PREPARED_NOT_PUBLISHED", "id": ident, "sha256": bundle["sha256"],
                "preview": str(folder / "PREVIEW.md"), "repository": REPOSITORY,
                "base": bundle["base"], "branch": bundle["branch"], "file_count": len(items) + 2}

    @staticmethod
    def report(bundle):
        lines = ["# " + bundle["title"], "", "Delivery ID: `" + bundle["id"] + "`", "",
                 "Source-reported status: **" + bundle["reported_status"] + "**.",
                 "This bridge verifies delivery hashes, not scientific correctness. Final acceptance and merge belong to the user.",
                 "", bundle["summary"], "", "| File | SHA256 | Bytes |", "|---|---|---|" ]
        for item in bundle["files"]:
            lines.append("| [" + item["path"] + "](" + item["path"] + ") | `" + item["sha256"] + "` | " + str(item["bytes"]) + " |")
            if PurePosixPath(item["path"]).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                lines += ["", "![" + item["path"] + "](" + item["path"] + ")", ""]
        return "\n".join(lines) + "\n"

    def package(self, ident, expected):
        folder = self.directory(ident)
        bundle = load(folder / "package.json")
        without_hash = {k: v for k, v in bundle.items() if k != "sha256"}
        if (not HASH.fullmatch(str(expected)) or bundle.get("sha256") != expected
                or digest(canonical(without_hash)) != expected or bundle.get("owner") != OWNER
                or bundle.get("repository") != REPOSITORY or bundle.get("id") != task_id(ident)
                or bundle.get("branch") != "bgv/review/" + ident or bundle.get("prefix") != "reviews/" + ident
                or bundle.get("source_sha256") != manifest(self.root)["sha256"]):
            raise BridgeError("PACKAGE_OR_SOURCE_CHANGED")
        intake = self.directory(ident, "intake")
        if digest(read(intake / "ready.json", 64 * 1024)) != bundle["request_sha256"]:
            raise BridgeError("SOURCE_REQUEST_CHANGED")
        payloads = {}
        for item in bundle["files"]:
            name = relative(item["path"])
            data = read(folder / "files" / name)
            if (digest(data) != item["sha256"] or len(data) != item["bytes"]
                    or digest(read(intake / name)) != item["sha256"]):
                raise BridgeError("SOURCE_OR_PACKAGE_ARTIFACT_CHANGED")
            inspect_file(name, data)
            payloads[name] = data
        payloads["README.md"] = self.report(bundle).encode("utf-8")
        payloads["delivery-manifest.json"] = canonical({k: bundle[k] for k in
            ("schema", "id", "repository", "reported_status", "scientific_validation_by_bridge", "files", "sha256")}) + b"\n"
        return bundle, payloads

    def verify_release(self):
        active = load(self.runtime / "activation.json")
        source_sha = manifest(self.root)["sha256"]
        if active.get("owner") != OWNER or active.get("source_sha256") != source_sha:
            raise BridgeError("BRIDGE_NOT_ACTIVATED")
        review = load(self.runtime / "reviews" / active["review_id"] / "result.json")
        if (review.get("status") != "PASS" or review.get("source_sha256") != source_sha
                or review.get("tools_disabled") is not True or review.get("tests_sha256") != active.get("tests_sha256")
                or passing_tests(self.runtime / "verification" / "tests.json", source_sha) != active["tests_sha256"]):
            raise BridgeError("CURRENT_INDEPENDENT_REVIEW_REQUIRED")

    def verify_remote_commit(self, bundle, payloads, commit_sha):
        commit = self.api.request("GET", "repos/" + REPOSITORY + "/commits/" + commit_sha)
        expected = {bundle["prefix"] + "/" + name: git_blob_sha(data) for name, data in payloads.items()}
        files = commit.get("files")
        if (commit.get("sha") != commit_sha
                or [p.get("sha") for p in commit.get("parents", [])] != [bundle["base_commit"]]
                or type(files) is not list or len(files) != len(expected)
                or {f.get("filename"): f.get("sha") for f in files} != expected
                or any(f.get("status") != "added" for f in files)):
            raise BridgeError("REMOTE_COMMIT_FILE_BINDING_MISMATCH")

    def observe(self, bundle, state):
        branch = self.api.request("GET", "repos/" + REPOSITORY + "/git/ref/heads/" + bundle["branch"], missing=True)
        pulls = self.api.request("GET", "repos/" + REPOSITORY + "/pulls?state=all&head=JIMMY081105:" + bundle["branch"] + "&per_page=100")
        if type(pulls) is not list or len(pulls) > 1:
            raise BridgeError("PR_IDENTITY_AMBIGUOUS")
        if branch is not None:
            if (not state.get("commit_sha") or branch.get("object", {}).get("sha") != state["commit_sha"]):
                raise BridgeError("EXISTING_BRANCH_NOT_OWNED")
        if pulls:
            pr = pulls[0]
            if (pr.get("head", {}).get("sha") != state.get("commit_sha") or pr.get("head", {}).get("ref") != bundle["branch"]
                    or pr.get("head", {}).get("repo", {}).get("full_name") != REPOSITORY
                    or pr.get("base", {}).get("repo", {}).get("full_name") != REPOSITORY
                    or pr.get("base", {}).get("ref") != bundle["base"]
                    or not re.fullmatch(r"https://github.com/" + re.escape(REPOSITORY) + r"/pull/[1-9][0-9]*", pr.get("html_url", ""))):
                raise BridgeError("EXISTING_PR_NOT_OWNED")
            state.update(state="MERGED_BY_USER" if pr.get("merged_at") else "CLOSED_BY_USER" if pr.get("state") == "closed" else
                         "PUBLISHED_DRAFT" if pr.get("draft") is True else "OPEN_FOR_USER_REVIEW",
                         url=pr["html_url"], number=pr["number"], updated_at=now())
        return branch, pulls

    def publish(self, ident, expected, authorize=False):
        if authorize is not True:
            raise BridgeError("EXPLICIT_FIXED_PACKAGE_PUBLICATION_AUTHORIZATION_REQUIRED")
        with lock(self.runtime):
            self.verify_release()
            bundle, payloads = self.package(ident, expected)
            self.connection()  # Exact local root/origin and private remote rechecked before every write sequence.
            folder = self.directory(ident)
            state = load(folder / "state.json")
            branch, pulls = self.observe(bundle, state)
            if pulls:
                self.verify_remote_commit(bundle, payloads, state["commit_sha"])
                save(folder / "state.json", state)
                return state
            if state.get("state") in ("WRITE_INTENT", "NEEDS_RECONCILIATION"):
                raise BridgeError("RECONCILE_REQUIRED_NO_AUTOMATIC_REPLAY")

            def post(endpoint, payload, operation):
                state.update(state="WRITE_INTENT", operation=operation, updated_at=now())
                save(folder / "state.json", state)
                try:
                    result = self.api.request("POST", "repos/" + REPOSITORY + endpoint, payload)
                except BaseException:
                    state.update(state="NEEDS_RECONCILIATION", updated_at=now())
                    save(folder / "state.json", state)
                    raise
                return result

            if branch is None:
                # Reserved UUID namespace must be absent in the fixed base; never overwrite existing review files.
                existing = self.api.request("GET", "repos/" + REPOSITORY + "/contents/" + bundle["prefix"] + "?ref=" + bundle["base_commit"], missing=True)
                if existing is not None:
                    raise BridgeError("RESULT_PREFIX_ALREADY_EXISTS")
                tree_items = []
                for name, data in sorted(payloads.items()):
                    blob = post("/git/blobs", {"content": base64.b64encode(data).decode("ascii"), "encoding": "base64"}, "CREATE_BLOB")
                    if blob.get("sha") != git_blob_sha(data):
                        raise BridgeError("INVALID_BLOB_RESPONSE")
                    tree_items.append({"path": bundle["prefix"] + "/" + name, "mode": "100644", "type": "blob", "sha": blob["sha"]})
                tree = post("/git/trees", {"base_tree": bundle["base_tree"], "tree": tree_items}, "CREATE_TREE")
                if not SHA.fullmatch(str(tree.get("sha"))):
                    raise BridgeError("INVALID_TREE_RESPONSE")
                commit = post("/git/commits", {"message": "Review result " + ident, "tree": tree["sha"], "parents": [bundle["base_commit"]]}, "CREATE_COMMIT")
                if not SHA.fullmatch(str(commit.get("sha"))):
                    raise BridgeError("INVALID_COMMIT_RESPONSE")
                state["commit_sha"] = commit["sha"]
                self.verify_remote_commit(bundle, payloads, state["commit_sha"])
                # POST /git/refs only creates an absent ref. No update-ref, force, merge or delete operation exists.
                created = post("/git/refs", {"ref": "refs/heads/" + bundle["branch"], "sha": commit["sha"]}, "CREATE_BRANCH")
                if created.get("object", {}).get("sha") != commit["sha"]:
                    raise BridgeError("INVALID_BRANCH_RESPONSE")
            state.update(state="BRANCH_CREATED", updated_at=now())
            save(folder / "state.json", state)
            self.verify_remote_commit(bundle, payloads, state["commit_sha"])
            body = ("Result delivery only; scientific validation is not performed by this bridge.\n\n"
                    + bundle["summary"] + "\n\nSource-reported status: **" + bundle["reported_status"] + "**.\n\n"
                    + "[Open result report and images](https://github.com/" + REPOSITORY + "/blob/"
                    + state["commit_sha"] + "/" + bundle["prefix"] + "/README.md)\n\n"
                    + "Package SHA256: `" + expected + "`\n\nFinal review and merge: user. No research jobs were started or stopped.")
            post("/pulls", {"title": bundle["title"], "head": bundle["branch"], "base": bundle["base"],
                             "draft": True, "body": body}, "CREATE_DRAFT_PR")
            # Never trust a POST receipt alone: read back exact repo/head SHA/base and PR URL.
            _, pulls = self.observe(bundle, state)
            if not pulls:
                raise BridgeError("PR_READBACK_UNVERIFIED")
            save(folder / "state.json", state)
            return state

    def reconcile(self, ident, expected):
        with lock(self.runtime):
            bundle, payloads = self.package(ident, expected)
            self.connection()
            folder = self.directory(ident)
            state = load(folder / "state.json")
            branch, pulls = self.observe(bundle, state)
            if branch is not None or pulls:
                self.verify_remote_commit(bundle, payloads, state["commit_sha"])
            if not pulls:
                confirmed_branch = branch is not None and state.get("operation") == "CREATE_BRANCH"
                state.update(state="BRANCH_CREATED" if confirmed_branch else "NEEDS_RECONCILIATION", updated_at=now())
            save(folder / "state.json", state)
            return state  # Read-only remote reconciliation never retries an uncertain write.


def freeze(root, runtime, review_id):
    root, runtime = safe(root), safe(runtime)
    task_id(review_id)
    source = manifest(root)
    tests_sha = passing_tests(runtime / "verification/tests.json", source["sha256"])
    review = load(runtime / "reviews" / review_id / "result.json")
    if (review.get("status") != "PASS" or review.get("tools_disabled") is not True
            or review.get("source_sha256") != source["sha256"] or review.get("tests_sha256") != tests_sha):
        raise BridgeError("CURRENT_INDEPENDENT_REVIEW_REQUIRED")
    destination = safe(runtime / "snapshots" / source["sha256"] / "source")
    destination.mkdir(parents=True, exist_ok=False)
    for name in SOURCE_FILES:
        target = safe(destination / name)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = read(root / name, 1024 * 1024)
        if digest(data) != source["files"][name]:
            raise BridgeError("SOURCE_CHANGED_DURING_FREEZE")
        with target.open("xb") as stream:
            stream.write(data)
    if manifest(destination) != source or manifest(root) != source:
        raise BridgeError("SOURCE_CHANGED_DURING_FREEZE")
    activation = {"owner": OWNER, "source_sha256": source["sha256"], "source": str(destination),
                  "review_id": review_id, "tests_sha256": tests_sha, "activated_at": now()}
    if (runtime / "activation.json").exists():
        raise BridgeError("BRIDGE_ALREADY_ACTIVATED_NO_OVERWRITE")
    save(runtime / "activation.json", activation)
    return activation

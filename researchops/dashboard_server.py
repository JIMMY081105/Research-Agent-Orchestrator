"""Loopback status API; optional desktop-only fixed analyze_text admission."""
from __future__ import annotations

import copy
import datetime as dt
import json
import hmac
import os
from pathlib import Path
import threading
import time
import re
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .dashboard_gpu import collect_gpu, view as gpu_view
from .dashboard_state import read_state, process_identity
from .dashboard_bundle import safe_path
from .dashboard_tasks import TaskStore, TaskError, LIMITS
from .worker_store import Store as WorkerStore, WorkerError, merge_state

OWNER = "BGV.Windows.ResearchOps.UI.v1"


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_record(path, value):
    """Only owned UI state is persisted, never any controller record."""
    path = safe_path(path)
    if path.is_symlink() or path.is_junction():
        raise ValueError("UI_REPARSE_PATH")
    tmp = path.with_suffix(path.suffix + ".tmp")
    if tmp.is_symlink() or tmp.is_junction():
        raise ValueError("UI_REPARSE_PATH")
    with tmp.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


class StatusCache:
    """Requests copy a cache; only background workers read SQLite or run fixed SSH."""

    def __init__(self, runtime, config, state_reader=read_state, gpu_reader=collect_gpu, directory=None, bundle_sha256=None, worker=False):
        self.runtime = Path(runtime)
        self.directory = Path(directory) if directory is not None else self.runtime / "dashboard"
        self.bundle_sha256 = bundle_sha256
        self.worker_enabled = worker
        self.config = config
        self.state_reader, self.gpu_reader = state_reader, gpu_reader
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.state = {"schema": 1, "read_only": True, "observed_at": None,
                      "reason": "INITIALIZING", "engines": {}, "mission": {}, "controller": {}}
        self.last_gpu = None
        self.gpu_error = None
        self.gpu_checks = 0
        self.threads = []
        self.persisted = 0.0

    def sample_state(self):
        try:
            value = self.state_reader(self.runtime)
            if not isinstance(value, dict):
                raise ValueError("INVALID_STATE")
            if self.worker_enabled:
                value = merge_state(value, self.runtime)
        except Exception:
            value = {"schema": 1, "read_only": True, "observed_at": utc(),
                     "reason": "STATE_UNAVAILABLE", "engines": {}, "mission": {}, "controller": {}}
        with self.lock:
            self.state = value

    def sample_gpu(self):
        try:
            value = self.gpu_reader(self.config["ssh"], self.config["ssh_alias"], timeout=20)
        except Exception:
            value = {"status": "ERROR", "failure": "UNKNOWN", "observed_at": utc()}
        with self.lock:
            self.gpu_checks += 1
            if value.get("status") == "OK":
                self.last_gpu, self.gpu_error = value, None
            else:
                self.gpu_error = value

    def snapshot(self):
        with self.lock:
            value = copy.deepcopy(self.state)
            value["gpu"] = gpu_view(copy.deepcopy(self.last_gpu), copy.deepcopy(self.gpu_error))
            value["service"] = {"owner": OWNER, "pid": os.getpid(), "read_only": True,
                                "bundle_sha256": self.bundle_sha256,
                                "served_at": utc(), "gpu_checks": self.gpu_checks,
                                "state_poll_seconds": 2, "gpu_poll_seconds": 30,
                                "scope": "REGISTERED_ORCHESTRATOR_TASKS"}
        return value

    def _loop(self, sample, interval, persist=False):
        while not self.stop_event.is_set():
            sample()
            if persist and time.monotonic() - self.persisted > 30:
                try:
                    write_record(self.directory / "status.json", self.snapshot())
                    self.persisted = time.monotonic()
                except (OSError, ValueError):
                    pass
            self.stop_event.wait(interval)

    def start(self):
        for sample, interval, persist in ((self.sample_state, 2, True), (self.sample_gpu, 30, False)):
            thread = threading.Thread(target=self._loop, args=(sample, interval, persist), daemon=True)
            self.threads.append(thread)
            thread.start()

    def close(self):
        self.stop_event.set()
        # A pending fixed SSH owns its process and its own <=25s timeout.
        for thread in self.threads:
            thread.join(timeout=26)


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16
    allow_reuse_address = False

    def __init__(self, address, cache, resources, composer=None, worker=None):
        if address[0] != "127.0.0.1":
            raise ValueError("LOOPBACK_ONLY")
        self.cache, self.resources = cache, resources
        self.composer = composer
        self.worker = worker
        self.csrf_token = secrets.token_urlsafe(32) if composer is not None or worker is not None else None
        self.capacity = threading.BoundedSemaphore(12)
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self.capacity.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.capacity.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.capacity.release()

    def handle_error(self, request, client_address):
        # Never print request paths, credentials, Python tracebacks or model text.
        pass


class Handler(BaseHTTPRequestHandler):
    server_version = "BGV-Local-UI/1"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(4)

    def log_message(self, *args):
        pass

    def send_error(self, code, message=None, explain=None):
        self._reply(code, b'{"error":"HTTP_REQUEST_REJECTED"}', "application/json")

    def _reply(self, code, body, mime):
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; "
                         "style-src 'self' 'unsafe-inline'; img-src 'self'; connect-src 'self'; "
                         "font-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        self.wfile.flush()
        # Windows can reset an early-rejected POST connection while unread body
        # bytes remain in the socket, losing the already-written HTTP rejection.
        # Drain only rejected, undispatched data after the response, bounded in
        # both time and bytes. Never reinterpret it as another request.
        if code >= 400 and self.command in ('POST', 'PUT', 'PATCH') and not getattr(self, '_body_consumed', False):
            previous_timeout = self.connection.gettimeout()
            self.connection.settimeout(.05)
            deadline, remaining = time.monotonic() + .1, 1024 * 1024
            try:
                while remaining and time.monotonic() < deadline:
                    chunk = self.rfile.read1(min(4096, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
            except (OSError, ValueError):
                pass
            finally:
                self.connection.settimeout(previous_timeout)
        self.close_connection = True

    def _allowed(self):
        expected = "127.0.0.1:" + str(self.server.server_port)
        origins = self.headers.get_all("Origin", [])
        hosts = self.headers.get_all("Host", [])
        return (self.client_address[0] == "127.0.0.1" and hosts == [expected]
                and (not origins or origins == ["http://" + expected])
                and len(self.headers.get_all("Sec-Fetch-Site", [])) <= 1
                and self.headers.get("Sec-Fetch-Site", "none") in ("none", "same-origin"))

    def _json(self, code, value):
        self._reply(code, json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):
        if not self._allowed():
            self._reply(403, b'{"error":"LOCAL_ORIGIN_REQUIRED"}', "application/json")
            return
        if self.path == "/api/status":
            value = self.server.cache.snapshot()
            value.setdefault("service", {})["task_submission_enabled"] = self.server.composer is not None
            body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
            if len(body) > 1024 * 1024:
                self._reply(503, b'{"error":"STATUS_UNAVAILABLE"}', "application/json")
            else:
                self._reply(200, body, "application/json; charset=utf-8")
        elif self.path == "/api/health":
            self._reply(200, b'{"owner":"BGV.Windows.ResearchOps.UI.v1","read_only":true}', "application/json")
        elif self.path == "/api/worker/capabilities" and self.server.worker is not None:
            value = self.server.worker.capability()
            self._json(200, {**value, "csrf_token": self.server.csrf_token})
        elif (self.path == "/api/worker/status" or re.fullmatch(r"/api/worker/status/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", self.path)) and self.server.worker is not None:
            try:
                self._json(200, self.server.worker.status(self.path.rsplit("/", 1)[1] if self.path != "/api/worker/status" else None))
            except WorkerError as error:
                self._json(error.status, {"error": error.code})
            except (OSError, ValueError, TypeError, KeyError):
                self._json(503, {"error": "WORKER_STATUS_UNAVAILABLE"})
        elif self.path == "/api/composer":
            value = self.server.composer.capability() if self.server.composer is not None else {"enabled": False, "reason": "READ_ONLY_SCOPE", "limits": dict(LIMITS)}
            self._json(200, {**value, "csrf_token": self.server.csrf_token if value.get("enabled") is True else None})
        elif re.fullmatch(r"/api/tasks/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", self.path) and self.server.composer is not None:
            try:
                self._json(200, self.server.composer.get(self.path.rsplit("/", 1)[1]))
            except TaskError as error:
                self._json(error.status, {"error": error.code})
            except (OSError, ValueError, TypeError, KeyError, RecursionError):
                self._json(503, {"error": "TASK_STATUS_UNAVAILABLE"})
        elif self.path in self.server.resources:
            mime, body = self.server.resources[self.path]
            self._reply(200, body, mime)
        else:
            self._reply(404, b'{"error":"NOT_FOUND"}', "application/json")

    do_HEAD = do_GET

    def do_POST(self):
        worker_action = self.server.worker is not None and self.path in ("/api/worker/turns", "/api/worker/approval", "/api/worker/cancel")
        if not worker_action and (self.server.composer is None or self.path != "/api/tasks"):
            self._reply(405, b'{"error":"READ_ONLY"}', "application/json"); return
        expected = "http://127.0.0.1:" + str(self.server.server_port)
        tokens = self.headers.get_all("X-BGV-CSRF", [])
        if (not self._allowed() or self.headers.get_all("Origin", []) != [expected]
                or self.headers.get("Sec-Fetch-Site", "same-origin") != "same-origin"
                or len(tokens) != 1 or not re.fullmatch(r"[A-Za-z0-9_-]{40,64}", tokens[0])
                or not hmac.compare_digest(tokens[0], self.server.csrf_token)):
            self._json(403, {"error": "SAME_ORIGIN_CSRF_REQUIRED"}); return
        lengths = self.headers.get_all("Content-Length", [])
        types = self.headers.get_all("Content-Type", [])
        if (len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,8}", lengths[0])
                or self.headers.get_all("Transfer-Encoding", []) or self.headers.get_all("Content-Encoding", [])
                or self.headers.get_all("Expect", [])):
            self._json(400, {"error": "INVALID_BODY_FRAMING"}); return
        size = int(lengths[0])
        request_limit = 128 * 1024 if worker_action else LIMITS["request_bytes"]
        if not 1 <= size <= request_limit:
            self._json(413, {"error": "REQUEST_TOO_LARGE"}); return
        if len(types) != 1 or not re.fullmatch(r"application/json(?:;\s*charset=utf-8)?", types[0].lower()):
            self._json(415, {"error": "JSON_UTF8_REQUIRED"}); return
        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError("DUPLICATE_JSON_KEY")
                value[key] = item
            return value
        try:
            self._body_consumed = True
            raw = self.rfile.read(size)
            if len(raw) != size:
                raise ValueError("INCOMPLETE_BODY")
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                               parse_constant=lambda value: (_ for _ in ()).throw(ValueError("NONFINITE_JSON")))
            if worker_action:
                method = {"/api/worker/turns": self.server.worker.submit, "/api/worker/approval": self.server.worker.decide,
                          "/api/worker/cancel": self.server.worker.cancel}[self.path]
                result = method(value)
            else:
                result = self.server.composer.submit(value)
            self._json(202, result)
        except (TaskError, WorkerError) as error:
            self._json(error.status, {"error": error.code})
        except (ValueError, TypeError, UnicodeError, RecursionError):
            self._json(400, {"error": "INVALID_SUBMISSION"})
        except OSError:
            self._json(503, {"error": "SUBMISSION_UNAVAILABLE"})

    def _read_only(self):
        self._reply(405, b'{"error":"READ_ONLY"}', "application/json")
    do_PUT = _read_only
    do_PATCH = _read_only
    do_DELETE = _read_only
    do_OPTIONS = _read_only


def resources(asset_directory):
    from .dashboard_web import PAGE, CSS, JS
    from .worker_web import JS as WORKER_JS, CSS as WORKER_CSS
    return {"/": ("text/html; charset=utf-8", PAGE.encode("utf-8")),
            "/assets/dashboard.css": ("text/css; charset=utf-8", CSS.encode("utf-8")),
            "/assets/dashboard.js": ("text/javascript; charset=utf-8", JS.encode("utf-8")),
            "/assets/worker.js": ("text/javascript; charset=utf-8", WORKER_JS.encode("utf-8")),
            "/assets/worker.css": ("text/css; charset=utf-8", WORKER_CSS.encode("utf-8")),
            "/assets/david.jpg": ("image/jpeg", (Path(asset_directory) / "david.jpg").read_bytes()),
            "/assets/lucy.jpg": ("image/jpeg", (Path(asset_directory) / "lucy.jpg").read_bytes())}


def serve(runtime, config, assets, source_sha256, trigger, run_seconds=None, directory=None, composer=False):
    runtime = safe_path(runtime)
    ui_runtime = safe_path(directory if directory is not None else runtime / "dashboard")
    if ui_runtime not in (runtime / "dashboard", runtime / "desktop/service"):
        raise ValueError("OWNED_UI_DIRECTORY_REQUIRED")
    if type(composer) is not bool or (composer and ui_runtime != runtime / "desktop/service"):
        raise ValueError("DESKTOP_COMPOSER_SCOPE_REQUIRED")
    ui_runtime.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        raise RuntimeError("Windows required")
    import msvcrt
    with safe_path(ui_runtime / "service.lock").open("a+b") as lock:
        if lock.tell() == 0:
            lock.write(b"0"); lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise RuntimeError("UI_ALREADY_RUNNING") from None
        cache = StatusCache(runtime, config, directory=ui_runtime, bundle_sha256=source_sha256, worker=composer)
        server = LocalServer(("127.0.0.1", config["port"]), cache, resources(assets), composer=TaskStore(runtime) if composer else None,
                             worker=WorkerStore(runtime) if composer else None)
        record = {"owner": OWNER, "pid": os.getpid(), "birth": process_identity(os.getpid()),
                  "parent_pid": os.getppid(), "started_at": utc(),
                  "source_sha256": source_sha256, "trigger": trigger, "read_only": True,
                  "url": "http://127.0.0.1:" + str(server.server_port), "state": "RUNNING"}
        write_record(ui_runtime / "service.json", record)
        cache.start()
        timer = None
        if run_seconds:
            timer = threading.Timer(run_seconds, server.shutdown); timer.daemon = True; timer.start()
        try:
            server.serve_forever(poll_interval=.3)
        finally:
            if timer:
                timer.cancel()
            server.server_close(); cache.close()
            write_record(ui_runtime / "service.json", {**record, "state": "STOPPED", "stopped_at": utc()})
            lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)

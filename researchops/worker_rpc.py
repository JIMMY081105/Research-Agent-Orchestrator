"""Private stdio Codex App Server transport, owned Windows Job and bounded event stream."""
from __future__ import annotations
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time

from . import winproc as wp
from .worker_store import WorkerError, clean


class NativeProcess:
    def __init__(self, args, cwd, environment, on_start):
        if os.name != "nt":
            raise WorkerError("WINDOWS_REQUIRED")
        self.job = wp._owned_job(8192)
        self.process = None
        self.files = []
        pi, handles, attributes = wp.ProcessInfo(), [], None
        try:
            child_in, parent_in = wp._pipe(True)
            child_out, parent_out = wp._pipe(False)
            child_err, parent_err = wp._pipe(False)
            handles += [child_in, parent_in, child_out, parent_out, child_err, parent_err]
            size = C.c_size_t()
            wp.K.InitializeProcThreadAttributeList(None, 2, 0, C.byref(size))
            attributes = C.create_string_buffer(size.value)
            wp._check(wp.K.InitializeProcThreadAttributeList(attributes, 2, 0, C.byref(size)))
            inherit = (W.HANDLE * 3)(child_in, child_out, child_err)
            jobs = (W.HANDLE * 1)(self.job)
            wp._check(wp.K.UpdateProcThreadAttribute(attributes, 0, wp.ATTRIBUTE_HANDLE_LIST, inherit, C.sizeof(inherit), None, None))
            wp._check(wp.K.UpdateProcThreadAttribute(attributes, 0, wp.ATTRIBUTE_JOB_LIST, jobs, C.sizeof(jobs), None, None))
            startup = wp.StartupEx()
            startup.info.cb, startup.info.flags = C.sizeof(wp.StartupEx), 0x100
            startup.info.stdin, startup.info.stdout, startup.info.stderr = child_in, child_out, child_err
            startup.attributes = C.cast(attributes, C.c_void_p)
            block = C.create_unicode_buffer("".join(f"{k}={v}\0" for k, v in sorted(environment.items(), key=lambda x: x[0].upper())) + "\0")
            command = C.create_unicode_buffer(subprocess.list2cmdline([str(v) for v in args]))
            flags = wp.CREATE_SUSPENDED | wp.CREATE_UNICODE_ENVIRONMENT | wp.EXTENDED_STARTUPINFO_PRESENT | wp.CREATE_NO_WINDOW
            wp._check(wp.K.CreateProcessW(None, command, None, None, True, flags, block, str(cwd), C.byref(startup), C.byref(pi)))
            self.process, self.pid = pi.process, pi.pid
            member = W.BOOL()
            wp._check(wp.K.IsProcessInJob(self.process, self.job, C.byref(member)))
            if not member.value:
                raise WorkerError("WORKER_PROCESS_NOT_CONTAINED")
            birth = wp.identity(self.pid)
            if birth in (None, "UNKNOWN"):
                raise WorkerError("WORKER_PROCESS_IDENTITY_UNKNOWN")
            on_start(self.pid, birth)  # Durable identity before any executable instruction runs.
            import msvcrt
            self.stdin = os.fdopen(msvcrt.open_osfhandle(parent_in.value, 0), "wb", buffering=0)
            handles.remove(parent_in); self.files.append(self.stdin)
            self.stdout = os.fdopen(msvcrt.open_osfhandle(parent_out.value, os.O_RDONLY), "rb", buffering=0)
            handles.remove(parent_out); self.files.append(self.stdout)
            self.stderr = os.fdopen(msvcrt.open_osfhandle(parent_err.value, os.O_RDONLY), "rb", buffering=0)
            handles.remove(parent_err); self.files.append(self.stderr)
            for h in (child_in, child_out, child_err):
                wp.K.CloseHandle(h); handles.remove(h)
            if wp.K.ResumeThread(pi.thread) == 0xffffffff:
                raise WorkerError("WORKER_PROCESS_RESUME_FAILED")
        except BaseException:
            self.close()
            raise
        finally:
            if pi.thread:
                wp.K.CloseHandle(pi.thread)
            for h in handles:
                wp.K.CloseHandle(h)
            if attributes is not None:
                wp.K.DeleteProcThreadAttributeList(attributes)

    def alive(self):
        return self.process is not None and wp.K.WaitForSingleObject(self.process, 0) == 258

    def close(self):
        # Only our retained Job HANDLE is closed, never a process discovered by name/PID.
        if self.job:
            wp.K.CloseHandle(self.job); self.job = None
        for stream in self.files:
            try:
                stream.close()
            except OSError:
                pass
        self.files = []
        if self.process:
            wp.K.WaitForSingleObject(self.process, 5000)
            wp.K.CloseHandle(self.process); self.process = None


class Rpc:
    def __init__(self, executable, cwd, on_start):
        environment = dict(os.environ)
        for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_BASE_URL", "ANTHROPIC_BASE_URL",
                    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY"):
            environment.pop(key, None)
        args = [str(executable), "app-server", "--listen", "stdio://", "-c", 'model_provider="openai"',
                "-c", "features.shell_tool=true", "-c", "features.unified_exec=true",
                "-c", "features.code_mode=false", "-c", "features.code_mode_host=false",
                "-c", "features.multi_agent=false", "-c", "features.multi_agent_v2=false"]
        self.process = NativeProcess(args, cwd, environment, on_start)
        self.messages = queue.Queue(maxsize=1000)
        self.error = None
        self.serial = 0
        self.backlog = []
        self.write_lock = threading.Lock()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        threading.Thread(target=self._discard_stderr, daemon=True).start()
        try:
            self.call("initialize", {"clientInfo": {"name": "bgv_scene_control", "version": "0.2.0"},
                                     "capabilities": {"experimentalApi": True}})
            self.send({"method": "initialized", "params": {}})
            account = self.call("account/read", {"refreshToken": False})
            if account.get("account", {}).get("type") != "chatgpt":
                raise WorkerError("EXISTING_CHATGPT_LOGIN_REQUIRED")
        except BaseException:
            self.close(); raise

    def _read(self):
        try:
            while True:
                line = self.process.stdout.readline(1024 * 1024 + 1)
                if not line:
                    break
                if len(line) > 1024 * 1024:
                    self.error = "WORKER_EVENT_TOO_LARGE"; break
                value = json.loads(line)
                method = value.get("method", "")
                if "reasoning" in method.lower() or "analysis" in method.lower():
                    continue
                item = value.get("params", {}).get("item", {})
                if isinstance(item, dict) and item.get("type") == "reasoning":
                    continue
                try:
                    self.messages.put_nowait(value)
                except queue.Full:
                    self.error = "WORKER_EVENT_QUEUE_FULL"; break
        except (ValueError, OSError, TypeError):
            self.error = "WORKER_PROTOCOL_READ_FAILED"

    def _discard_stderr(self):
        # No raw provider/network diagnostics are persisted or exposed to the UI.
        try:
            while self.process.stderr.read(4096):
                pass
        except (OSError, ValueError):
            pass

    def send(self, value):
        data = (json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        if len(data) > 256 * 1024:
            raise WorkerError("WORKER_REQUEST_TOO_LARGE")
        try:
            with self.write_lock:
                self.process.stdin.write(data); self.process.stdin.flush()
        except OSError:
            raise WorkerError("WORKER_CONNECTION_LOST") from None

    def call(self, method, params, timeout=45):
        self.serial += 1
        request_id = self.serial
        self.send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.error:
                raise WorkerError(self.error)
            try:
                value = self.messages.get(timeout=.2)
            except queue.Empty:
                if not self.process.alive():
                    raise WorkerError("WORKER_PROCESS_EXITED")
                continue
            if value.get("id") == request_id and "method" not in value:
                if "error" in value:
                    # Return fixed categories; no provider/credential response dump.
                    raise WorkerError("WORKER_RPC_REJECTED_" + str(value["error"].get("code", "UNKNOWN")).replace("-", "N"))
                return value.get("result", {})
            if len(self.backlog) >= 1000:
                raise WorkerError("WORKER_EVENT_QUEUE_FULL")
            self.backlog.append(value)
        raise WorkerError("WORKER_RPC_TIMEOUT")

    def drain(self):
        values, self.backlog = self.backlog, []
        while len(values) < 1000:
            try:
                values.append(self.messages.get_nowait())
            except queue.Empty:
                break
        if self.error:
            raise WorkerError(self.error)
        return values

    def respond(self, request_id, result):
        self.send({"id": request_id, "result": result})

    def close(self):
        self.process.close()

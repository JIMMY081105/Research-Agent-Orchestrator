"""Windows process identity and containment. Never enumerate or terminate old jobs."""
import ctypes as C
from ctypes import wintypes as W
import msvcrt
import os
import subprocess
import threading
import time

if os.name == "nt":
    K = C.WinDLL("kernel32", use_last_error=True)
    K.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    K.OpenProcess.restype = W.HANDLE
    K.CloseHandle.argtypes = [W.HANDLE]
    K.GetProcessTimes.argtypes = [W.HANDLE] + [C.POINTER(W.FILETIME)] * 4
    K.GetExitCodeProcess.argtypes = [W.HANDLE, C.POINTER(W.DWORD)]
    K.CreateJobObjectW.argtypes = [C.c_void_p, W.LPCWSTR]
    K.CreateJobObjectW.restype = W.HANDLE
    K.SetInformationJobObject.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD]
    K.TerminateJobObject.argtypes = [W.HANDLE, W.UINT]
    K.IsProcessInJob.argtypes = [W.HANDLE, W.HANDLE, C.POINTER(W.BOOL)]
    K.CreatePipe.argtypes = [C.POINTER(W.HANDLE), C.POINTER(W.HANDLE), C.c_void_p, W.DWORD]
    K.SetHandleInformation.argtypes = [W.HANDLE, W.DWORD, W.DWORD]
    K.InitializeProcThreadAttributeList.argtypes = [C.c_void_p, W.DWORD, W.DWORD, C.POINTER(C.c_size_t)]
    K.UpdateProcThreadAttribute.argtypes = [C.c_void_p, W.DWORD, C.c_size_t, C.c_void_p, C.c_size_t,
                                            C.c_void_p, C.c_void_p]
    K.DeleteProcThreadAttributeList.argtypes = [C.c_void_p]
    K.CreateProcessW.argtypes = [W.LPCWSTR, W.LPWSTR, C.c_void_p, C.c_void_p, W.BOOL, W.DWORD,
                                 C.c_void_p, W.LPCWSTR, C.c_void_p, C.c_void_p]
    K.ResumeThread.argtypes = [W.HANDLE]
    K.ResumeThread.restype = W.DWORD
    K.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
    K.WaitForSingleObject.restype = W.DWORD
    K.GetCurrentProcess.restype = W.HANDLE
    K.LocalFree.argtypes = [C.c_void_p]
    A = C.WinDLL("advapi32", use_last_error=True)
    A.OpenProcessToken.argtypes = [W.HANDLE, W.DWORD, C.POINTER(W.HANDLE)]
    A.DuplicateTokenEx.argtypes = [W.HANDLE, W.DWORD, C.c_void_p, C.c_int, C.c_int, C.POINTER(W.HANDLE)]
    A.ConvertStringSidToSidW.argtypes = [W.LPCWSTR, C.POINTER(C.c_void_p)]
    A.GetLengthSid.argtypes = [C.c_void_p]
    A.GetLengthSid.restype = W.DWORD
    A.SetTokenInformation.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD]
    A.CreateProcessAsUserW.argtypes = [W.HANDLE, W.LPCWSTR, W.LPWSTR, C.c_void_p, C.c_void_p, W.BOOL, W.DWORD,
                                       C.c_void_p, W.LPCWSTR, C.c_void_p, C.c_void_p]


def identity(pid):
    """Return creation FILETIME for a live PID, None if dead, UNKNOWN if inaccessible."""
    if os.name != "nt":
        raise RuntimeError("Windows required")
    h = K.OpenProcess(0x1000, False, int(pid))
    if not h:
        return None if C.get_last_error() == 87 else "UNKNOWN"
    try:
        code = W.DWORD()
        if not K.GetExitCodeProcess(h, C.byref(code)):
            return "UNKNOWN"
        if code.value != 259:
            return None
        times = [W.FILETIME() for _ in range(4)]
        if not K.GetProcessTimes(h, *(C.byref(t) for t in times)):
            return "UNKNOWN"
        return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
    finally:
        K.CloseHandle(h)


class Limits(C.Structure):
    _fields_ = [("process_time", C.c_int64), ("job_time", C.c_int64),
                ("flags", W.DWORD), ("min_working", C.c_size_t),
                ("max_working", C.c_size_t), ("active", W.DWORD),
                ("affinity", C.c_size_t), ("priority", W.DWORD), ("sched", W.DWORD)]


class IO(C.Structure):
    _fields_ = [(n, C.c_uint64) for n in ("read_ops", "write_ops", "other_ops",
                                         "read_bytes", "write_bytes", "other_bytes")]


class Extended(C.Structure):
    _fields_ = [("basic", Limits), ("io", IO), ("process_memory", C.c_size_t),
                ("job_memory", C.c_size_t), ("peak_process", C.c_size_t),
                ("peak_job", C.c_size_t)]


class Security(C.Structure):
    _fields_ = [("length", W.DWORD), ("descriptor", C.c_void_p), ("inherit", W.BOOL)]


class Startup(C.Structure):
    _fields_ = [("cb", W.DWORD), ("reserved", W.LPWSTR), ("desktop", W.LPWSTR), ("title", W.LPWSTR),
                ("x", W.DWORD), ("y", W.DWORD), ("x_size", W.DWORD), ("y_size", W.DWORD),
                ("x_chars", W.DWORD), ("y_chars", W.DWORD), ("fill", W.DWORD), ("flags", W.DWORD),
                ("show", W.WORD), ("reserved2_size", W.WORD), ("reserved2", C.c_void_p),
                ("stdin", W.HANDLE), ("stdout", W.HANDLE), ("stderr", W.HANDLE)]


class StartupEx(C.Structure):
    _fields_ = [("info", Startup), ("attributes", C.c_void_p)]


class ProcessInfo(C.Structure):
    _fields_ = [("process", W.HANDLE), ("thread", W.HANDLE), ("pid", W.DWORD), ("tid", W.DWORD)]


CREATE_SUSPENDED, CREATE_UNICODE_ENVIRONMENT = 0x4, 0x400
EXTENDED_STARTUPINFO_PRESENT, CREATE_NO_WINDOW = 0x80000, 0x08000000
ATTRIBUTE_HANDLE_LIST, ATTRIBUTE_JOB_LIST = 0x20002, 0x2000D


class SidAndAttributes(C.Structure):
    _fields_ = [("sid", C.c_void_p), ("attributes", W.DWORD)]


class SecurityCapabilities(C.Structure):
    _fields_ = [("sid", C.c_void_p), ("capabilities", C.c_void_p),
                ("count", W.DWORD), ("reserved", W.DWORD)]


LOW_INTEGRITY_SID = "S-1-16-4096"
ICACLS = r"C:\Windows\System32\icacls.exe"


def low_integrity_token():
    """A primary token equal to ours but at Low integrity: it cannot write to the user's
    ordinary (Medium) files or directories, only to objects explicitly labelled Low."""
    token, low, sid = W.HANDLE(), W.HANDLE(), C.c_void_p()
    _check(A.OpenProcessToken(K.GetCurrentProcess(), 0x0001 | 0x0002 | 0x0008 | 0x0080, C.byref(token)))
    try:
        _check(A.DuplicateTokenEx(token, 0x02000000, None, 2, 1, C.byref(low)))
        _check(A.ConvertStringSidToSidW(LOW_INTEGRITY_SID, C.byref(sid)))
        label = SidAndAttributes(sid, 0x20)  # SE_GROUP_INTEGRITY
        _check(A.SetTokenInformation(low, 25, C.byref(label), C.sizeof(label) + A.GetLengthSid(sid)))
        return low
    except BaseException:
        if low:
            K.CloseHandle(low)
        raise
    finally:
        K.CloseHandle(token)
        if sid:
            K.LocalFree(sid)


def label_low(directory):
    """Make one fresh directory (and what is created inside it) writable at Low integrity.

    Only this directory's own ACL changes: OWNER RIGHTS gains full control so the owner may set
    the mandatory label (WRITE_OWNER), then the label is lowered to Low with inheritance."""
    for args in (["/grant", "*S-1-3-4:(OI)(CI)F"], ["/setintegritylevel", "(OI)(CI)low"]):
        done = subprocess.run([ICACLS, str(directory), *args], capture_output=True, creationflags=0x08000000)
        if done.returncode != 0:
            raise RuntimeError("Could not label the tool output directory")


def label_medium(directory):
    """Return a tool directory and everything in it to Medium: no later Low process can write it."""
    done = subprocess.run([ICACLS, str(directory), "/setintegritylevel", "(OI)(CI)medium", "/T", "/C", "/Q"],
                          capture_output=True, creationflags=0x08000000)
    if done.returncode != 0:
        raise RuntimeError("Could not restore the tool output directory label")


def checkpoint(stage, pid):
    """No-op in production. Fault-injection tests replace it to kill the controller at a boundary."""


def _check(ok):
    if not ok:
        raise C.WinError(C.get_last_error())


def _pipe(child_reads):
    read, write = W.HANDLE(), W.HANDLE()
    sa = Security(C.sizeof(Security), None, True)
    _check(K.CreatePipe(C.byref(read), C.byref(write), C.byref(sa), 0))
    parent = write if child_reads else read
    try:
        _check(K.SetHandleInformation(parent, 1, 0))  # only the child's end stays inheritable
    except BaseException:
        K.CloseHandle(read)
        K.CloseHandle(write)
        raise
    return (read, write) if child_reads else (write, read)  # (child end, parent end)


def _owned_job(memory_mb):
    job = K.CreateJobObjectW(None, None)
    if not job:
        raise C.WinError(C.get_last_error())
    limits = Extended()
    limits.basic.flags = 0x2000 | 0x200 | 0x8  # kill-on-close, job memory, process cap
    limits.basic.active = 8
    limits.job_memory = memory_mb * 1024 * 1024
    if not K.SetInformationJobObject(job, 9, C.byref(limits), C.sizeof(limits)):
        K.CloseHandle(job)
        raise C.WinError(C.get_last_error())
    return job


# Fixed combined stdout+stderr bound; independent of model-controlled input.
OWNED_OUTPUT_LIMIT_BYTES = 8 * 1024 * 1024
OWNED_OUTPUT_LIMIT_EXIT = 111
_PIPE_CHUNK_BYTES = 16 * 1024


class _BoundedCapture:
    def __init__(self):
        self.lock = threading.Lock()
        self.chunks = {"out": bytearray(), "err": bytearray()}
        self.total = 0
        self.overflow = threading.Event()
        self.failed = threading.Event()

    def discard(self):
        with self.lock:
            self.chunks["out"].clear()
            self.chunks["err"].clear()

    def drain(self, stream, key):
        try:
            while True:
                data = os.read(stream.fileno(), _PIPE_CHUNK_BYTES)
                if not data:
                    return
                with self.lock:
                    if self.overflow.is_set():
                        continue
                    if len(data) > OWNED_OUTPUT_LIMIT_BYTES - self.total:
                        # No raw output survives rejection, including earlier valid-looking text.
                        self.chunks["out"].clear()
                        self.chunks["err"].clear()
                        self.overflow.set()
                        continue
                    self.chunks[key].extend(data)
                    self.total += len(data)
        except OSError:
            self.failed.set()

    def result(self):
        with self.lock:
            return tuple(self.chunks[key].decode("utf-8", "replace") for key in ("out", "err"))


class _OwnedPipeThread(threading.Thread):
    """Keep an actual owned thread HANDLE, avoiding cancellation by a reusable thread ID."""
    def __init__(self, *args, capture, **kwargs):
        super().__init__(*args, **kwargs)
        self.io_handle = None
        self.capture = capture

    def run(self):
        K.OpenThread.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        K.OpenThread.restype = W.HANDLE
        # This code runs on the very thread being opened, so its ID cannot have been reused.
        self.io_handle = K.OpenThread(0x0001, False, threading.get_native_id())
        if not self.io_handle:
            self.capture.failed.set()
            return
        try:
            super().run()
        except BaseException:
            self.capture.failed.set()


def _cancel_pipe_threads(workers):
    """Cancel only synchronous I/O belonging to our retained reader/writer thread handles."""
    K.CancelSynchronousIo.argtypes = [W.HANDLE]
    K.CancelSynchronousIo.restype = W.BOOL
    for thread in workers:
        if thread.is_alive() and thread.io_handle:
            K.CancelSynchronousIo(thread.io_handle)


def run_owned(argv, prompt, cwd, env, timeout, on_start, memory_mb=4096, low_integrity=False,
              appcontainer_sid=None, appcontainer_capabilities=None):
    """Create a suspended child already in our private kill-on-close Job, register its
    identity, then resume it. Capture streams incrementally under one fixed byte budget.
    A rejected capture returns only a fixed error code/string, never any raw model output.
    Low integrity alone is not filesystem confinement; callers need an actual sandbox.
    """
    if os.name != "nt":
        raise RuntimeError("Windows required")
    if appcontainer_sid and (low_integrity or appcontainer_capabilities is None):
        raise ValueError("AppContainer requires its explicit capabilities and no alternate token")
    job = _owned_job(memory_mb)
    handles, files, workers, pi = [], [], [], ProcessInfo()
    attributes, token, capture = None, None, _BoundedCapture()
    try:
        # Token creation belongs inside this try: failure must also close our private Job.
        token = low_integrity_token() if low_integrity else None
        child_in, parent_in = _pipe(True)
        handles += [child_in, parent_in]
        child_out, parent_out = _pipe(False)
        handles += [child_out, parent_out]
        child_err, parent_err = _pipe(False)
        handles += [child_err, parent_err]
        size = C.c_size_t()
        attribute_count = 4 if appcontainer_sid else 2
        K.InitializeProcThreadAttributeList(None, attribute_count, 0, C.byref(size))
        attributes = C.create_string_buffer(size.value)
        _check(K.InitializeProcThreadAttributeList(attributes, attribute_count, 0, C.byref(size)))
        inherit = (W.HANDLE * 3)(child_in, child_out, child_err)
        jobs = (W.HANDLE * 1)(job)
        _check(K.UpdateProcThreadAttribute(attributes, 0, ATTRIBUTE_HANDLE_LIST, inherit, C.sizeof(inherit), None, None))
        _check(K.UpdateProcThreadAttribute(attributes, 0, ATTRIBUTE_JOB_LIST, jobs, C.sizeof(jobs), None, None))
        if appcontainer_sid:
            capabilities = SecurityCapabilities(appcontainer_sid, C.cast(appcontainer_capabilities, C.c_void_p),
                                                len(appcontainer_capabilities), 0)
            opt_out = W.DWORD(1)  # LPAC: no ALL APPLICATION PACKAGES blanket grants
            _check(K.UpdateProcThreadAttribute(attributes, 0, 0x20009, C.byref(capabilities),
                                               C.sizeof(capabilities), None, None))
            _check(K.UpdateProcThreadAttribute(attributes, 0, 0x2000F, C.byref(opt_out),
                                               C.sizeof(opt_out), None, None))
        startup = StartupEx()
        startup.info.cb = C.sizeof(StartupEx)
        startup.info.flags = 0x100
        startup.info.stdin, startup.info.stdout, startup.info.stderr = child_in, child_out, child_err
        startup.attributes = C.cast(attributes, C.c_void_p)
        block = C.create_unicode_buffer("".join(f"{k}={v}\0" for k, v in sorted(env.items(), key=lambda kv: kv[0].upper())) + "\0")
        command = C.create_unicode_buffer(subprocess.list2cmdline([str(a) for a in argv]))
        flags = CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT | EXTENDED_STARTUPINFO_PRESENT | CREATE_NO_WINDOW
        if token is not None:
            _check(A.CreateProcessAsUserW(token, None, command, None, None, True, flags, block, str(cwd),
                                        C.byref(startup), C.byref(pi)))
        else:
            _check(K.CreateProcessW(None, command, None, None, True, flags, block, str(cwd),
                                   C.byref(startup), C.byref(pi)))
        checkpoint("created", pi.pid)
        member = W.BOOL()
        _check(K.IsProcessInJob(pi.process, job, C.byref(member)))
        if not member.value:
            raise RuntimeError("Child is not contained by its private job")
        for h in (child_in, child_out, child_err):
            K.CloseHandle(h)
            handles.remove(h)
        on_start(pi.pid, identity(pi.pid))
        checkpoint("registered", pi.pid)
        out_f = os.fdopen(msvcrt.open_osfhandle(parent_out.value, os.O_RDONLY), "rb", buffering=0)
        handles.remove(parent_out); files.append(out_f)
        err_f = os.fdopen(msvcrt.open_osfhandle(parent_err.value, os.O_RDONLY), "rb", buffering=0)
        handles.remove(parent_err); files.append(err_f)
        in_f = os.fdopen(msvcrt.open_osfhandle(parent_in.value, 0), "wb", buffering=0)
        handles.remove(parent_in); files.append(in_f)

        def feed():
            try:
                data = memoryview(prompt.encode("utf-8"))
                while data:
                    written = in_f.write(data[:_PIPE_CHUNK_BYTES])
                    if not written:
                        break
                    data = data[written:]
            except OSError:
                pass
            finally:
                in_f.close()

        workers = [_OwnedPipeThread(target=capture.drain, args=(out_f, "out"), daemon=True, capture=capture),
                   _OwnedPipeThread(target=capture.drain, args=(err_f, "err"), daemon=True, capture=capture),
                   _OwnedPipeThread(target=feed, daemon=True, capture=capture)]
        for thread in workers:
            thread.start()
        if K.ResumeThread(pi.thread) == 0xFFFFFFFF:
            raise C.WinError(C.get_last_error())
        started = time.monotonic()
        deadline, code, parent_finished = started + timeout, W.DWORD(), False
        failure = None
        while True:
            if capture.overflow.is_set():
                failure = (OWNED_OUTPUT_LIMIT_EXIT, "OWNED_PROCESS_OUTPUT_LIMIT")
                break
            if capture.failed.is_set():
                failure = (109, "OWNED_PROCESS_CAPTURE_FAILED")
                break
            if not parent_finished:
                status = K.WaitForSingleObject(pi.process, 0)
                if status == 0:
                    _check(K.GetExitCodeProcess(pi.process, C.byref(code)))
                    parent_finished = True
                    # A grandchild must not keep our capture pipes alive after its parent exits.
                    # The Job is ours; no unrelated process is enumerated or terminated.
                    _check(K.TerminateJobObject(job, 0))
                elif status != 258:
                    raise RuntimeError("Owned process wait failed")
            if parent_finished and not any(thread.is_alive() for thread in workers):
                # A last drain may have crossed the limit since this iteration's first
                # flag check. Once all workers ended these flags are final.
                if capture.overflow.is_set():
                    failure = (OWNED_OUTPUT_LIMIT_EXIT, "OWNED_PROCESS_OUTPUT_LIMIT")
                elif capture.failed.is_set():
                    failure = (109, "OWNED_PROCESS_CAPTURE_FAILED")
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                failure = (1460, "OWNED_PROCESS_TIMEOUT")
                break
            time.sleep(min(0.02, remaining))
        if failure is not None:
            capture.discard()
            _check(K.TerminateJobObject(job, failure[0]))
            K.WaitForSingleObject(pi.process, 5000)
            for thread in workers:
                thread.join(0.25)
            if any(thread.is_alive() for thread in workers):
                _cancel_pipe_threads(workers)
                for thread in workers:
                    thread.join(0.25)
            capture.discard()
            return failure[0], "", failure[1], time.monotonic() - started
        out, err = capture.result()
        return code.value, out, err, time.monotonic() - started
    finally:
        K.CloseHandle(job)
        if pi.process:
            K.WaitForSingleObject(pi.process, 5000)
            K.CloseHandle(pi.process)
        if pi.thread:
            K.CloseHandle(pi.thread)
        if any(thread.is_alive() for thread in workers):
            _cancel_pipe_threads(workers)
            for thread in workers:
                if thread.ident is not None:
                    thread.join(0.25)
        for thread in workers:
            if thread.io_handle:
                K.CloseHandle(thread.io_handle)
                thread.io_handle = None
        for stream in files:
            try:
                stream.close()
            except OSError:
                pass
        for h in handles:
            K.CloseHandle(h)
        if attributes is not None:
            K.DeleteProcThreadAttributeList(attributes)
        if token is not None:
            K.CloseHandle(token)

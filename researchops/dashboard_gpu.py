"""Bounded, read-only SQZ GPU telemetry for the local dashboard.

This module starts only its own short-lived SSH process. It never attaches to an
existing SSH master, dispatches research work, or interprets model/user commands.
An empty compute-process list is an observation, not proof of task completion.
"""

import csv
from datetime import datetime, timezone
import io
import json
import math
from pathlib import Path
import re
import shlex
import subprocess


FAILURES = frozenset({"UNKNOWN", "NETWORK", "AUTH", "TIMEOUT", "HOSTKEY", "INVALID_DATA"})
STALE_SECONDS = 90
MAX_RESPONSE_BYTES = 262144
SSH_OPTIONS = (
    "BatchMode=yes", "NumberOfPasswordPrompts=0", "StrictHostKeyChecking=yes",
    "UpdateHostKeys=no", "PermitLocalCommand=no", "ForwardAgent=no",
    "ForwardX11=no", "ClearAllForwardings=yes", "ControlMaster=no",
    "ControlPath=none", "ControlPersist=no", "ProxyCommand=none", "ProxyJump=none",
    "RemoteCommand=none", "SendEnv=-*", "ConnectTimeout=8", "ConnectionAttempts=1",
    "ServerAliveInterval=5", "ServerAliveCountMax=1", "RequestTTY=no",
)
GPU_QUERY = (
    "nvidia-smi",
    "--query-gpu=index,uuid,name,utilization.gpu,memory.used,memory.total,temperature.gpu",
    "--format=csv,noheader,nounits",
)
PROCESS_QUERY = (
    "nvidia-smi", "--query-compute-apps=pid,used_gpu_memory,gpu_uuid",
    "--format=csv,noheader,nounits",
)

# The remote program and both query argument lists are constants. Its subprocesses
# have their own deadlines and discard stderr at source; no environment or process
# command lines are read. -I/-B avoid cwd imports and bytecode writes on the server.
REMOTE_PROBE = """import json,subprocess
QUERIES = %r
def query(argv):
    try:
        result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, timeout=6)
        return {'exit_code': result.returncode, 'stdout': result.stdout}
    except subprocess.TimeoutExpired:
        return {'exit_code': 124, 'stdout': ''}
    except OSError:
        return {'exit_code': 127, 'stdout': ''}
results = [query(argv) for argv in QUERIES]
print(json.dumps({'gpu': results[0], 'compute_processes': results[1]}, separators=(',', ':')))
""" % ([list(GPU_QUERY), list(PROCESS_QUERY)],)
REMOTE_COMMAND = "/usr/bin/python3 -I -B -c " + shlex.quote(REMOTE_PROBE)
_GPU_UUID = re.compile(r"GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z")
_ALIAS = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z")
_INTEGER = re.compile(r"-?[0-9]{1,12}\Z")


def _now():
    return datetime.now(timezone.utc)


def _stamp(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _time(value):
    if isinstance(value, datetime):
        result = value
    elif type(value) in (int, float) and math.isfinite(value):
        result = datetime.fromtimestamp(value, timezone.utc)
    elif isinstance(value, str) and len(value) <= 64:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("Invalid telemetry timestamp")
    if result.tzinfo is None:
        raise ValueError("Telemetry timestamps require a timezone")
    return result.astimezone(timezone.utc)


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("Invalid telemetry number")
    return value


def _number(text, low, high):
    if not isinstance(text, str) or not _INTEGER.fullmatch(text.strip()):
        raise ValueError("Invalid telemetry number")
    return _integer(int(text.strip()), low, high)


def _gpu(row):
    expected = {"index", "uuid", "name", "utilization_percent", "memory_used_mib",
                "memory_total_mib", "temperature_c"}
    if not isinstance(row, dict) or set(row) != expected:
        raise ValueError("Invalid GPU fields")
    _integer(row["index"], 0, 4095)
    if not isinstance(row["uuid"], str) or not _GPU_UUID.fullmatch(row["uuid"]):
        raise ValueError("Invalid GPU identity")
    name = row["name"]
    if not isinstance(name, str) or not 1 <= len(name) <= 120 or not all(c.isprintable() for c in name):
        raise ValueError("Invalid GPU name")
    _integer(row["utilization_percent"], 0, 100)
    total = _integer(row["memory_total_mib"], 1, 1048576)
    _integer(row["memory_used_mib"], 0, total)
    _integer(row["temperature_c"], -40, 150)
    return {key: row[key] for key in expected}


def _sample(gpus, processes):
    if not isinstance(gpus, list) or not 1 <= len(gpus) <= 256:
        raise ValueError("Invalid GPU list")
    if not isinstance(processes, list) or len(processes) > 8192:
        raise ValueError("Invalid process list")
    clean_gpus = [_gpu(row) for row in gpus]
    by_uuid = {row["uuid"]: row for row in clean_gpus}
    if len(by_uuid) != len(clean_gpus) or len({row["index"] for row in clean_gpus}) != len(clean_gpus):
        raise ValueError("Duplicate GPU identity")
    clean_processes = []
    seen = set()
    for row in processes:
        if not isinstance(row, dict) or set(row) != {"pid", "memory_used_mib", "gpu_uuid"}:
            raise ValueError("Invalid process fields")
        pid = _integer(row["pid"], 1, 2147483647)
        gpu_uuid = row["gpu_uuid"]
        if not isinstance(gpu_uuid, str) or gpu_uuid not in by_uuid:
            raise ValueError("Unknown process GPU")
        used = _integer(row["memory_used_mib"], 0, by_uuid[gpu_uuid]["memory_total_mib"])
        if (pid, gpu_uuid) in seen:
            raise ValueError("Duplicate process identity")
        seen.add((pid, gpu_uuid))
        clean_processes.append({"pid": pid, "memory_used_mib": used, "gpu_uuid": gpu_uuid})
    return clean_gpus, clean_processes


def _parse(gpu_csv, process_csv):
    if not isinstance(gpu_csv, str) or not isinstance(process_csv, str):
        raise ValueError("Invalid query output")
    gpus = []
    for fields in csv.reader(io.StringIO(gpu_csv), skipinitialspace=True, strict=True):
        if not fields:
            continue
        if len(fields) != 7:
            raise ValueError("Invalid GPU query columns")
        fields = [field.strip() for field in fields]
        gpus.append({"index": _number(fields[0], 0, 4095), "uuid": fields[1], "name": fields[2],
                     "utilization_percent": _number(fields[3], 0, 100),
                     "memory_used_mib": _number(fields[4], 0, 1048576),
                     "memory_total_mib": _number(fields[5], 1, 1048576),
                     "temperature_c": _number(fields[6], -40, 150)})
    processes = []
    for fields in csv.reader(io.StringIO(process_csv), skipinitialspace=True, strict=True):
        if not fields:
            continue
        if len(fields) != 3:
            raise ValueError("Invalid process query columns")
        fields = [field.strip() for field in fields]
        processes.append({"pid": _number(fields[0], 1, 2147483647),
                          "memory_used_mib": _number(fields[1], 0, 1048576), "gpu_uuid": fields[2]})
    return _sample(gpus, processes)


def _failure(reason):
    return {"status": "ERROR", "failure": reason, "observed_at": _stamp(_now())}


def _classify(stderr):
    # Only fixed enums leave this function; raw banners/authentication errors do not.
    lowered = stderr.lower()
    if any(term in lowered for term in ("host key verification failed", "host identification has changed",
                                       "no host key is known", "offending host key")):
        return "HOSTKEY"
    if any(term in lowered for term in ("permission denied", "authentication failed", "too many authentication failures",
                                       "no supported authentication", "agent refused operation", "signing failed")):
        return "AUTH"
    if any(term in lowered for term in ("connection timed out", "connection refused", "connection reset",
                                       "connection closed", "could not resolve hostname", "network is unreachable",
                                       "no route to host", "connection aborted")):
        return "NETWORK"
    return "UNKNOWN"


def _reap_own(process):
    """Kill only the Popen object created by this collector; never kill by PID/name."""
    try:
        process.kill()
    except OSError:
        pass
    try:
        process.communicate(timeout=2)
    except (subprocess.TimeoutExpired, OSError):
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        try:
            process.wait(timeout=1)
        except (subprocess.TimeoutExpired, OSError):
            pass


def collect_gpu(ssh_path, alias="sunmingyuan1", timeout=20):
    """Return sanitized GPU data or a fixed failure enum, with no implicit retries.

    ssh_path and alias are trusted local configuration, never HTTP parameters.
    The SSH wait is capped at 22 seconds, reserving at most three seconds to reap
    this collector's process. The remote queries each have a six-second deadline.
    """
    try:
        path = Path(ssh_path)
        if not path.is_absolute() or path.name.lower() not in ("ssh", "ssh.exe") or "\x00" in str(path):
            return _failure("UNKNOWN")
        if not isinstance(alias, str) or not _ALIAS.fullmatch(alias):
            return _failure("UNKNOWN")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            return _failure("UNKNOWN")
        bounded_timeout = min(float(timeout), 22.0)
        command = [str(path), "-n", "-T"]
        for option in SSH_OPTIONS:
            command.extend(("-o", option))
        command.extend((alias, REMOTE_COMMAND))
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, shell=False, close_fds=True,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, TypeError, ValueError):
        return _failure("UNKNOWN")
    try:
        stdout, stderr = process.communicate(timeout=bounded_timeout)
    except subprocess.TimeoutExpired:
        _reap_own(process)
        return _failure("TIMEOUT")
    except OSError:
        _reap_own(process)
        return _failure("UNKNOWN")
    if len(stdout) + len(stderr) > MAX_RESPONSE_BYTES:
        return _failure("INVALID_DATA")
    if process.returncode != 0:
        return _failure(_classify(stderr.decode("utf-8", "replace")))
    try:
        payload = json.loads(stdout.decode("utf-8", "strict"))
        if not isinstance(payload, dict) or set(payload) != {"gpu", "compute_processes"}:
            raise ValueError("Invalid query envelope")
        codes = []
        for key in ("gpu", "compute_processes"):
            row = payload[key]
            if not isinstance(row, dict) or set(row) != {"exit_code", "stdout"} or type(row["exit_code"]) is not int:
                raise ValueError("Invalid query result")
            codes.append(row["exit_code"])
        if any(code != 0 for code in codes):
            return _failure("TIMEOUT" if 124 in codes else "UNKNOWN")
        gpus, processes = _parse(payload["gpu"]["stdout"], payload["compute_processes"]["stdout"])
    except (ValueError, UnicodeError, TypeError, csv.Error, OverflowError):
        return _failure("INVALID_DATA")
    return {"status": "OK", "observed_at": _stamp(_now()), "gpus": gpus, "processes": processes}


def view(last_success=None, last_error=None, now=None):
    """Project cached samples; never initiate SSH from a dashboard HTTP request.

    OK/DEGRADED describe freshness/transport only, not research task success. A
    failure retains the last good GPU values and timestamp. At 90 seconds their
    status becomes STALE. Without a valid sample, no synthetic zeroes are returned.
    """
    current = _now() if now is None else _time(now)
    failure = None
    checked_at = None
    error_at = None
    if last_error is not None:
        try:
            if last_error.get("status") != "ERROR" or last_error.get("failure") not in FAILURES:
                raise ValueError("Invalid cached failure")
            error_at = _time(last_error["observed_at"])
            failure = last_error["failure"]
            checked_at = _stamp(error_at)
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            failure = "INVALID_DATA"
    result = {"status": "UNAVAILABLE", "observed_at": None, "last_checked_at": checked_at,
              "age_seconds": None, "gpus": [], "processes": [], "failure": failure}
    if last_success is None:
        return result
    try:
        if last_success.get("status") != "OK":
            raise ValueError("Invalid cached sample")
        sampled_at = _time(last_success["observed_at"])
        if sampled_at > current:
            raise ValueError("Future telemetry is not fresh evidence")
        gpus, processes = _sample(last_success["gpus"], last_success["processes"])
        age = (current - sampled_at).total_seconds()
        if error_at is None or error_at < sampled_at:
            failure = None if error_at is not None else failure
            checked_at = _stamp(sampled_at)
        status = "STALE" if age >= STALE_SECONDS else ("DEGRADED" if failure else "OK")
        result.update(status=status, observed_at=_stamp(sampled_at), last_checked_at=checked_at,
                      age_seconds=round(age, 3), gpus=gpus, processes=processes, failure=failure)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        result["failure"] = "INVALID_DATA"
    return result

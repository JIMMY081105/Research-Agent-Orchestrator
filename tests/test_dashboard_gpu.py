"""Failure-oriented tests; no SSH connections or research processes are started."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shlex
import subprocess
import unittest
from unittest.mock import Mock, patch

from researchops import dashboard_gpu as gpu


SSH = str(Path(r"C:\windows\System32\OpenSSH\ssh.exe"))
UUID = "GPU-d2fb89ec-2f57-9cb4-967b-7fd58d744c70"
UUID2 = "GPU-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
GPU_CSV = f"0, {UUID}, NVIDIA A40, 25, 4330, 46068, 39\n"
PROCESS_CSV = f"54013, 4322, {UUID}\n"
NOW = datetime(2026, 10, 19, 20, 42, 19, tzinfo=timezone.utc)


def payload(gpus=GPU_CSV, processes=PROCESS_CSV, gpu_code=0, process_code=0):
    return json.dumps({"gpu": {"exit_code": gpu_code, "stdout": gpus},
                       "compute_processes": {"exit_code": process_code, "stdout": processes}}).encode()


class DashboardGpuTests(unittest.TestCase):
    def run_collect(self, stdout=None, stderr=b"", code=0, **kwargs):
        child = Mock()
        child.returncode = code
        child.communicate.return_value = (payload() if stdout is None else stdout, stderr)
        with patch.object(gpu.subprocess, "Popen", return_value=child) as popen:
            with patch.object(gpu, "_now", return_value=NOW):
                row = gpu.collect_gpu(SSH, **kwargs)
        return row, popen, child

    def sample(self):
        return self.run_collect()[0]

    def test_realistic_sample_and_timestamp_no_raw_output(self):
        row, popen, child = self.run_collect(stderr=b"UNTRUSTED_BANNER_MUST_NOT_SAVE")
        self.assertEqual("OK", row["status"])
        self.assertEqual("2026-10-19T20:42:19Z", row["observed_at"])
        self.assertEqual(25, row["gpus"][0]["utilization_percent"])
        self.assertEqual(4330, row["gpus"][0]["memory_used_mib"])
        self.assertEqual({"pid": 54013, "memory_used_mib": 4322, "gpu_uuid": UUID}, row["processes"][0])
        self.assertNotIn("UNTRUSTED", json.dumps(row))
        self.assertNotIn("stdout", json.dumps(row))
        popen.assert_called_once()
        child.kill.assert_not_called()

    def test_fixed_queries_and_safe_ssh_options(self):
        _, popen, child = self.run_collect()
        args = popen.call_args.args[0]
        self.assertEqual([SSH, "-n", "-T"], args[:3])
        self.assertEqual(["sunmingyuan1", gpu.REMOTE_COMMAND], args[-2:])
        for required in ("BatchMode=yes", "StrictHostKeyChecking=yes", "UpdateHostKeys=no",
                         "ClearAllForwardings=yes", "ControlMaster=no", "ControlPath=none",
                         "ControlPersist=no", "PermitLocalCommand=no", "ForwardAgent=no",
                         "ForwardX11=no", "ProxyCommand=none", "ProxyJump=none", "SendEnv=-*",
                         "RemoteCommand=none", "ConnectionAttempts=1"):
            self.assertIn(required, args)
        self.assertNotIn("-O", args)
        self.assertNotIn("-R", args)
        self.assertNotIn("-L", args)
        self.assertFalse(popen.call_args.kwargs["shell"])
        self.assertEqual(subprocess.DEVNULL, popen.call_args.kwargs["stdin"])
        self.assertTrue(popen.call_args.kwargs["close_fds"])
        self.assertNotIn("env", popen.call_args.kwargs)
        self.assertEqual(getattr(subprocess, "CREATE_NO_WINDOW", 0), popen.call_args.kwargs["creationflags"])
        child.communicate.assert_called_once_with(timeout=20.0)
        command = shlex.split(args[-1])
        self.assertEqual(["/usr/bin/python3", "-I", "-B", "-c"], command[:4])
        self.assertEqual(gpu.REMOTE_PROBE, command[4])
        self.assertIn(repr([list(gpu.GPU_QUERY), list(gpu.PROCESS_QUERY)]), command[4])
        for forbidden in ("/proc/", "/environ", "os.environ", "kill-session", "sbatch", "srun ", "pip install"):
            self.assertNotIn(forbidden, command[4])

    def test_multiple_gpus_and_one_pid_on_each_gpu(self):
        gpus = GPU_CSV + f"1,{UUID2},NVIDIA A40,0,0,46068,30\n"
        processes = PROCESS_CSV + f"54013,12,{UUID2}\n"
        row, _, _ = self.run_collect(payload(gpus, processes))
        self.assertEqual("OK", row["status"])
        self.assertEqual(2, len(row["gpus"]))
        self.assertEqual(2, len(row["processes"]))

    def test_no_compute_processes_and_zero_utilization_are_only_observations(self):
        row, _, _ = self.run_collect(payload(GPU_CSV.replace(", 25,", ", 0,"), ""))
        self.assertEqual("OK", row["status"])
        self.assertEqual([], row["processes"])
        serialized = json.dumps(gpu.view(row, now=NOW)).lower()
        for unsupported in ("completed", "finished", "research_pass", "task_success"):
            self.assertNotIn(unsupported, serialized)

    def test_invalid_gpu_values_fail_without_synthetic_zeroes(self):
        cases = [
            "", GPU_CSV.replace(", 25,", ", 101,"), GPU_CSV.replace(", 25,", ", -1,"),
            GPU_CSV.replace(", 4330,", ", 99999,"), GPU_CSV.replace(", 46068,", ", 0,"),
            GPU_CSV.replace(", 39", ", 151"), GPU_CSV.replace(", 39", ", N/A"),
            GPU_CSV.replace(UUID, "not-a-uuid"), GPU_CSV.replace("0,", "-1,", 1),
            GPU_CSV.replace(", 25,", ", NaN,"), GPU_CSV.replace(", 25,", ", Infinity,"),
            GPU_CSV.replace("NVIDIA A40", "bad\x00name"), GPU_CSV + GPU_CSV,
            GPU_CSV + GPU_CSV.replace(UUID, UUID2), GPU_CSV + GPU_CSV.replace("0,", "1,", 1),
            GPU_CSV.replace(", 25,", ", 0.0,"), GPU_CSV.replace("NVIDIA A40", '"unterminated'),
        ]
        for raw in cases:
            with self.subTest(raw=raw):
                row, _, _ = self.run_collect(payload(raw, ""))
                self.assertEqual("INVALID_DATA", row["failure"])
                self.assertNotIn("gpus", row)

    def test_invalid_process_values_or_unregistered_gpu_fail(self):
        cases = [PROCESS_CSV.replace("54013", "0"), PROCESS_CSV.replace("54013", "-1"),
                 PROCESS_CSV.replace("4322", "999999"), PROCESS_CSV.replace("4322", "N/A"),
                 PROCESS_CSV.replace(UUID, UUID2), PROCESS_CSV + PROCESS_CSV, "1,2\n"]
        for raw in cases:
            with self.subTest(raw=raw):
                row, _, _ = self.run_collect(payload(processes=raw))
                self.assertEqual("INVALID_DATA", row["failure"])

    def test_both_query_exit_codes_are_required(self):
        for gpu_code, process_code in ((1, 0), (0, 1), (1, 1), (127, 0), (0, 124), (124, 0)):
            with self.subTest(gpu_code=gpu_code, process_code=process_code):
                row, _, _ = self.run_collect(payload(gpu_code=gpu_code, process_code=process_code))
                self.assertEqual("ERROR", row["status"])
                self.assertEqual("TIMEOUT" if 124 in (gpu_code, process_code) else "UNKNOWN", row["failure"])
                self.assertNotIn("gpus", row)

    def test_ssh_failures_classified_without_retaining_private_errors(self):
        cases = {"Permission denied (publickey)": "AUTH", "Too many authentication failures": "AUTH",
                 "Host key verification failed": "HOSTKEY", "REMOTE HOST IDENTIFICATION HAS CHANGED": "HOSTKEY",
                 "Connection timed out": "NETWORK", "Connection refused": "NETWORK",
                 "Could not resolve hostname": "NETWORK", "Network is unreachable": "NETWORK",
                 "some unknown error": "UNKNOWN"}
        for message, expected in cases.items():
            with self.subTest(message=message):
                row, _, child = self.run_collect(stderr=(message + " FAKE_SECRET_SENTINEL").encode(), code=255)
                self.assertEqual(expected, row["failure"])
                self.assertNotIn("FAKE_SECRET", json.dumps(row))
                child.kill.assert_not_called()

    def test_timeout_only_kills_new_owned_popen_and_does_not_retry(self):
        own_child = Mock()
        own_child.communicate.side_effect = [subprocess.TimeoutExpired("ssh", 20), (b"", b"")]
        old_session = Mock()
        with patch.object(gpu.subprocess, "Popen", return_value=own_child) as popen:
            row = gpu.collect_gpu(SSH)
        self.assertEqual("TIMEOUT", row["failure"])
        popen.assert_called_once()
        own_child.kill.assert_called_once_with()
        self.assertEqual([unittest.mock.call(timeout=20.0), unittest.mock.call(timeout=2)], own_child.communicate.call_args_list)
        old_session.kill.assert_not_called()

    def test_requested_timeout_cannot_exceed_cleanup_budget(self):
        _, _, child = self.run_collect(timeout=10000)
        child.communicate.assert_called_once_with(timeout=22.0)

    def test_bad_local_parameters_never_spawn_any_process(self):
        with patch.object(gpu.subprocess, "Popen") as popen:
            for alias in ("-oAnything", "sunmingyuan1;whoami", "sunmingyuan1 -R 1", "bad\nname", "", None):
                self.assertEqual("UNKNOWN", gpu.collect_gpu(SSH, alias=alias)["failure"])
            for timeout in (0, -1, float("nan"), float("inf"), True, "20"):
                self.assertEqual("UNKNOWN", gpu.collect_gpu(SSH, timeout=timeout)["failure"])
            for path in ("ssh.exe", "anything.exe", str(Path(SSH).with_name("powershell.exe")), None):
                self.assertEqual("UNKNOWN", gpu.collect_gpu(path)["failure"])
            popen.assert_not_called()

    def test_missing_ssh_is_explicit_unknown(self):
        with patch.object(gpu.subprocess, "Popen", side_effect=FileNotFoundError("FAKE_PRIVATE_PATH")):
            row = gpu.collect_gpu(SSH)
        self.assertEqual("UNKNOWN", row["failure"])
        self.assertNotIn("FAKE_PRIVATE", json.dumps(row))

    def test_invalid_envelopes_oversized_output_and_utf8_fail(self):
        cases = [b"not JSON FAKE_PRIVATE", b"\xff", b"[]", b"{}", b"x" * (gpu.MAX_RESPONSE_BYTES + 1),
                 payload().replace(b'"exit_code": 0', b'"exit_code": true'),
                 payload().replace(b'"stdout":', b'"stderr":', 1),
                 payload().replace(b'"stdout": "0,', b'"stdout": null, "extra": "0,', 1)]
        for raw in cases:
            with self.subTest(raw_length=len(raw)):
                row, _, _ = self.run_collect(raw)
                self.assertEqual("INVALID_DATA", row["failure"])
                self.assertNotIn("FAKE_PRIVATE", json.dumps(row))

    def test_cached_view_90_second_stale_boundary_no_ssh_or_research_claims(self):
        sample = self.sample()
        with patch.object(gpu.subprocess, "Popen", side_effect=AssertionError("View attempted SSH")):
            fresh = gpu.view(sample, now=NOW + timedelta(seconds=89))
            stale = gpu.view(sample, now=NOW + timedelta(seconds=90))
        self.assertEqual("OK", fresh["status"])
        self.assertEqual("STALE", stale["status"])
        self.assertEqual(sample["gpus"], stale["gpus"])
        self.assertEqual(sample["observed_at"], stale["observed_at"])
        self.assertEqual(90, stale["age_seconds"])

    def test_new_failure_preserves_last_good_data_and_timestamp(self):
        sample = self.sample()
        error = {"status": "ERROR", "failure": "NETWORK", "observed_at": gpu._stamp(NOW + timedelta(seconds=20))}
        row = gpu.view(sample, error, NOW + timedelta(seconds=30))
        self.assertEqual("DEGRADED", row["status"])
        self.assertEqual("NETWORK", row["failure"])
        self.assertEqual(sample["gpus"], row["gpus"])
        self.assertEqual(sample["observed_at"], row["observed_at"])
        self.assertEqual(error["observed_at"], row["last_checked_at"])
        row = gpu.view(sample, error, NOW + timedelta(seconds=100))
        self.assertEqual("STALE", row["status"])
        self.assertEqual("NETWORK", row["failure"])

    def test_old_error_does_not_override_new_success(self):
        error = {"status": "ERROR", "failure": "AUTH", "observed_at": gpu._stamp(NOW - timedelta(seconds=5))}
        row = gpu.view(self.sample(), error, NOW)
        self.assertEqual("OK", row["status"])
        self.assertIsNone(row["failure"])

    def test_no_success_returns_unavailable_without_fabricated_metrics(self):
        self.assertEqual("UNAVAILABLE", gpu.view(now=NOW)["status"])
        error = {"status": "ERROR", "failure": "HOSTKEY", "observed_at": gpu._stamp(NOW)}
        row = gpu.view(last_error=error, now=NOW)
        self.assertEqual([], row["gpus"])
        self.assertEqual([], row["processes"])
        self.assertIsNone(row["observed_at"])
        self.assertEqual("HOSTKEY", row["failure"])

    def test_view_rejects_invalid_or_future_cached_samples(self):
        sample = self.sample()
        for malformed in ({}, {**sample, "observed_at": "unknown"},
                          {**sample, "observed_at": gpu._stamp(NOW + timedelta(seconds=1))},
                          {**sample, "gpus": [{**sample["gpus"][0], "raw_private": "FAKE_SECRET"}]}):
            row = gpu.view(malformed, now=NOW)
            self.assertEqual("UNAVAILABLE", row["status"])
            self.assertEqual("INVALID_DATA", row["failure"])
            self.assertNotIn("FAKE_SECRET", json.dumps(row))


if __name__ == "__main__":
    unittest.main()

"""A dashboard read must not mutate, disclose results, or infer activity from PID."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from researchops import dashboard_state as dashboard

NOW = dt.datetime(2026, 10, 20, 3, 0, tzinfo=dt.timezone.utc)
STAMP = (NOW - dt.timedelta(seconds=75)).isoformat()
SECRET = "PRIVATE_PROMPT_RESULT_TOKEN_SENTINEL"


class DashboardStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runtime = Path(self.temp.name)
        self.database = self.runtime / "queue.sqlite3"
        self.connection = sqlite3.connect(self.database)
        self.addCleanup(self.connection.close)
        self.connection.executescript("""
          CREATE TABLE tasks(id TEXT PRIMARY KEY,spec TEXT,state TEXT,reworks INTEGER,reason TEXT,created TEXT,updated TEXT);
          CREATE TABLE attempts(id TEXT PRIMARY KEY,task TEXT,stage TEXT,engine TEXT,session TEXT,pid INTEGER,birth TEXT,state TEXT,created TEXT,result TEXT);
          CREATE TABLE calls(id TEXT PRIMARY KEY,day TEXT,purpose TEXT,created TEXT);
          CREATE TABLE call_engines(call TEXT PRIMARY KEY,engine TEXT,task TEXT,stage TEXT);
          CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);
        """)
        self.task = str(uuid.uuid4())
        self.connection.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?)", (self.task, json.dumps({"input": SECRET}), "EXECUTING", 0, None, STAMP, STAMP))
        self.connection.commit()

    def write(self, relative, value):
        path = self.runtime / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def attempt(self, state="RUNNING", engine="codex", pid=123, birth="134368509797913032", session=None):
        identifier = str(uuid.uuid4())
        self.connection.execute("INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?,?,?)", (identifier, self.task,
            "execute" if engine == "codex" else "review", engine, session or str(uuid.uuid4()), pid, birth, state, STAMP, SECRET))
        self.connection.commit()
        return identifier

    def read(self, probe=None):
        return dashboard.read_state(self.runtime, identity_probe=probe or (lambda pid: "134368509797913032"), now=NOW)

    def test_live_requires_registered_pid_and_birth(self):
        self.attempt()
        state = self.read()
        agent = state["engines"]["codex"]
        self.assertEqual(agent["state"], "RUNNING")
        self.assertEqual(agent["active_attempts"][0]["identity_state"], "VERIFIED_LIVE")
        self.assertEqual(agent["active_attempts"][0]["elapsed_seconds"], 75)
        self.assertEqual(state["mission"]["active_task_ids"], [self.task])
        self.assertEqual(state["engines"]["claude"]["state"], "IDLE")

    def test_dead_reused_and_unknown_processes_are_never_running(self):
        self.attempt()
        for returned, expected in ((None, "NOT_LIVE"), ("134368509797913033", "PID_REUSED"), ("UNKNOWN", "UNKNOWN")):
            with self.subTest(returned=returned):
                agent = self.read(lambda pid: returned)["engines"]["codex"]
                self.assertEqual(agent["state"], "UNKNOWN")
                self.assertEqual(agent["active_attempts"], [])
                self.assertEqual(agent["unverified_attempts"][0]["identity_state"], expected)

    def test_starting_without_identity_is_not_alive(self):
        self.attempt(state="STARTING", pid=None, birth=None)
        agent = self.read()["engines"]["codex"]
        self.assertEqual(agent["state"], "STARTING")
        self.assertEqual(agent["active_attempts"], [])

    def test_completed_attempt_is_historical_and_does_not_probe_pid(self):
        self.attempt(state="COMPLETED")
        probe = lambda pid: self.fail("Historical PID must not be probed or reported live")
        agent = self.read(probe)["engines"]["codex"]
        self.assertEqual(agent["state"], "IDLE")
        self.assertEqual(agent["last_attempt"]["identity_state"], "HISTORICAL_NOT_CHECKED")

    def test_invalid_session_never_claims_live(self):
        self.attempt(session=SECRET)
        agent = self.read()["engines"]["codex"]
        self.assertEqual(agent["state"], "UNKNOWN")
        self.assertIsNone(agent["last_attempt"]["session"])
        self.assertNotIn(SECRET, json.dumps(agent))

    def test_probe_failure_is_unknown(self):
        self.attempt()
        def fail(pid):
            raise OSError(SECRET)
        state = self.read(fail)
        self.assertEqual(state["engines"]["codex"]["state"], "UNKNOWN")
        self.assertNotIn(SECRET, json.dumps(state))

    def test_no_raw_fields_or_machine_credentials_are_exposed(self):
        self.attempt(state="COMPLETED")
        self.write("machine.json", {"token": SECRET})
        self.write("STATUS.json", {"secret": SECRET})
        self.write("activation.json", {"owner": dashboard.OWNER, "source_sha256": "a" * 64,
            "source": SECRET, "time": STAMP, "previous_activation": {"raw": SECRET}})
        state = self.read()
        dumped = json.dumps(state)
        self.assertNotIn(SECRET, dumped)
        self.assertNotIn('"spec"', dumped)
        self.assertNotIn('"result"', dumped)
        self.assertEqual(state["controller"]["source_sha256"], "a" * 64)
        self.assertEqual(state["external_sessions"]["state"], "UNKNOWN")
        self.assertTrue(state["external_sessions"]["unregistered_presence_only"])

    def test_read_does_not_write_database_or_other_files(self):
        self.attempt()
        self.write("STATUS.json", {"unchanged": True})
        before = {path.relative_to(self.runtime).as_posix(): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in self.runtime.rglob("*") if path.is_file()}
        statements = []
        connect = sqlite3.connect
        def capture(*args, **kwargs):
            self.assertTrue(kwargs["uri"])
            self.assertIn("?mode=ro", args[0])
            connection = connect(*args, **kwargs)
            connection.set_trace_callback(statements.append)
            return connection
        with patch.object(dashboard.sqlite3, "connect", side_effect=capture):
            self.assertEqual(self.read()["controller"]["database"], "OK")
        after = {path.relative_to(self.runtime).as_posix(): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in self.runtime.rglob("*") if path.is_file()}
        self.assertEqual(before, after)
        self.assertIn("PRAGMA query_only=ON", statements)
        self.assertFalse(any(sql.startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER")) for sql in statements))

    def test_missing_database_does_not_get_created(self):
        missing = self.runtime / "never-created"
        state = dashboard.read_state(missing, now=NOW)
        self.assertEqual(state["controller"]["database"], "UNKNOWN")
        self.assertFalse(missing.exists())

    def test_corrupt_database_is_unknown(self):
        self.connection.close()
        self.database.write_bytes(b"corrupt database " + SECRET.encode())
        state = self.read()
        self.assertEqual(state["controller"]["database"], "UNKNOWN")
        self.assertEqual(state["engines"]["codex"]["state"], "UNKNOWN")
        self.assertNotIn(SECRET, json.dumps(state))

    def test_wrong_schema_is_unknown_and_never_migrated(self):
        self.connection.execute("DROP TABLE attempts")
        self.connection.commit()
        before = self.database.read_bytes()
        state = self.read()
        self.assertEqual(state["controller"]["database"], "UNKNOWN")
        self.assertEqual(self.database.read_bytes(), before)
        tables = {row[0] for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn("attempts", tables)

    def test_oversized_or_deep_metadata_fails_closed(self):
        path = self.runtime / "research-watch" / "latest.json"
        path.parent.mkdir()
        for data in ("x" * (2 * 1024 * 1024 + 1), "{\"nested\":" + "[" * 1100 + "0" + "]" * 1100 + "}"):
            with self.subTest(length=len(data)):
                path.write_text(data, encoding="utf-8")
                state = self.read()
                self.assertTrue(state["research_observer"]["stale"])
                self.assertEqual(state["research_observer"]["transport"], "UNKNOWN")

    def test_reparse_paths_are_not_read(self):
        with patch.object(Path, "is_symlink", return_value=True), patch.object(dashboard.sqlite3, "connect") as connect:
            state = self.read()
            connect.assert_not_called()
            self.assertEqual(state["controller"]["database"], "UNKNOWN")

    def test_budget_counts_legacy_and_failed_reviews_without_refunds(self):
        purposes = [(str(uuid.uuid4()) + ":review", None), ("independent-review:old", None),
            ("cycle-review:old", None), ("codex-audit-dev:old", None), ("task", "review"),
            ("task", "independent-review")]
        for index in range(51):
            purpose, stage = purposes[index % len(purposes)]
            identifier = str(uuid.uuid4())
            self.connection.execute("INSERT INTO calls VALUES(?,?,?,?)", (identifier, NOW.date().isoformat(), purpose, STAMP))
            if stage:
                self.connection.execute("INSERT INTO call_engines VALUES(?,?,?,?)", (identifier, "claude", self.task, stage))
        self.connection.execute("INSERT INTO calls VALUES(?,?,?,?)", (str(uuid.uuid4()), "2026-10-19", "cycle-review:yesterday", STAMP))
        self.connection.commit()
        reviews = self.read()["controller"]["daily_reviews"]
        self.assertEqual(reviews, {"day": "2026-10-20", "used": 51, "limit": 50, "remaining": 0})

    def test_pause_does_not_hide_still_live_process(self):
        self.attempt()
        self.connection.execute("INSERT INTO meta VALUES(?,?)", ("engine_pause:codex", json.dumps({"reason": "QUOTA", "extra": SECRET})))
        self.connection.commit()
        agent = self.read()["engines"]["codex"]
        self.assertEqual(agent["state"], "RUNNING")
        self.assertEqual(agent["paused"], {"reason": "QUOTA"})
        self.assertNotIn(SECRET, json.dumps(agent))

    def test_observer_cache_fresh_stale_and_signal_filtering(self):
        def report(age):
            return {"observed_at": (NOW - dt.timedelta(seconds=age)).isoformat(), "transport": "OK",
                "reason": "STATIC_READONLY_PROBE", "host": SECRET, "read_only": True,
                "processes": [{"state": "LIVE", "arguments": SECRET}, {"state": "EXITED"}],
                "known_files": [{"path": SECRET, "progress": {"signals": ["ENTIRE_TASK_STOP_REQUIRED", SECRET]}}]}
        for age in (30, 1300):
            with self.subTest(age=age):
                self.write("research-watch/latest.json", report(age))
                value = self.read()["research_observer"]
                self.assertEqual(value["stale"], age > dashboard.STALE_SECONDS)
                self.assertEqual(value["age_seconds"], age)
                self.assertEqual(value["process_counts"], {"LIVE": 1, "EXITED": 1, "UNKNOWN": 0})
                self.assertEqual(value["progress_signals"], ["ENTIRE_TASK_STOP_REQUIRED"])
                self.assertNotIn(SECRET, json.dumps(value))

    def test_future_and_malformed_cache_are_not_live(self):
        for report in ({"observed_at": (NOW + dt.timedelta(days=1)).isoformat(), "processes": []},
                       {"observed_at": STAMP, "processes": SECRET}):
            with self.subTest(report=report):
                self.write("research-watch/latest.json", report)
                value = self.read()["research_observer"]
                self.assertTrue(value["stale"])
                self.assertEqual(value["transport"], "UNKNOWN")

    def test_active_attempt_row_limit_fails_closed(self):
        for index in range(dashboard.MAX_ATTEMPTS + 1):
            self.attempt()
        value = self.read()
        self.assertEqual(value["controller"]["database"], "UNKNOWN")
        self.assertEqual(value["engines"]["codex"]["active_attempts"], [])


if __name__ == "__main__":
    unittest.main()

"""Fixed command admission, durable deduplication and final-output binding tests."""
import json
import contextlib
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
import uuid
from unittest.mock import Mock, patch

from researchops import dashboard_tasks as tasks
from researchops.core import expected


class ComposerTasksTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.runtime = Path(self.temporary.name)
        policy = {"actions": ["analyze_text"], "gpu": False, "research_write": False, "publish": False, "max_input_bytes": 32768}
        source_files = {"researchops.py": b"# mock controller entry, never executed\n", "config/policy.json": tasks.canonical(policy)}
        hashes = {name: tasks.digest(data) for name, data in source_files.items()}
        self.sha = tasks.digest(tasks.canonical(hashes))
        self.source = self.runtime / "snapshots" / self.sha / "source"
        for relative, data in source_files.items():
            path = self.source / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
        self.write(self.runtime / "activation.json", {"owner": "BGV.Windows.ResearchOps.v1", "source_sha256": self.sha,
            "source": str(self.source), "source_manifest": {"files": hashes, "sha256": self.sha}})
        with self.database() as connection:
            connection.execute("CREATE TABLE tasks(id PRIMARY KEY,spec,state,reason,created,updated)")
        self.calls = []
        self.store = tasks.TaskStore(self.runtime, admitter=self.admit)
        self.request = {"id": str(uuid.uuid4()), "prompt": "请根据材料比较两个方案。", "context": "方案甲使用CPU。方案乙使用GPU，但GPU未授权。", "writer": "codex"}

    @staticmethod
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(tasks.canonical(value))

    @contextlib.contextmanager
    def database(self):
        connection = sqlite3.connect(self.runtime / "queue.sqlite3")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def admit(self, argv, started, cwd):
        self.calls.append(argv)
        self.assertEqual(argv[0], r"C:\Python312\python.exe")
        self.assertEqual(argv[1:3], ["-B", str(self.source / "researchops.py")])
        self.assertEqual(argv[argv.index("--action") + 1], "analyze_text")
        self.assertNotIn("run", argv); self.assertNotIn("tick", argv)
        self.assertNotIn(self.request["prompt"], argv)
        data = json.loads(Path(argv[argv.index("--input-file") + 1]).read_text(encoding="utf-8"))
        self.assertEqual(set(data), {"text", "question"})
        self.assertIn("summary", expected("analyze_text", data))
        task = argv[argv.index("--id") + 1]
        writer = argv[argv.index("--writer") + 1]
        spec = {"id": task, "action": "analyze_text", "input": data, "input_sha256": tasks.digest(tasks.canonical(data)),
            "writer": writer, "reviewer": "claude" if writer == "codex" else "codex", "source": {"sha256": self.sha}}
        started(1234567, "134369208842965739")
        with self.database() as connection:
            connection.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?)", (task, json.dumps(spec), "QUEUED", None, tasks.stamp(), tasks.stamp()))
        return 0

    def test_valid_submission_uses_real_core_schema_and_only_fixed_submit(self):
        result = self.store.submit(self.request)
        self.assertEqual((result["state"], result["writer"], result["reviewer"]), ("QUEUED", "codex", "claude"))
        self.assertFalse(result["duplicate"])
        self.assertEqual(len(self.calls), 1)
        capability = self.store.capability()
        self.assertTrue(capability["enabled"])
        self.assertFalse(capability["starts_execution"])

    def test_empty_context_uses_prompt_as_literal_source_and_writer_can_swap(self):
        self.request.update(context="", writer="claude")
        result = self.store.submit(self.request)
        data = json.loads((self.store.directory / self.request["id"] / "input.json").read_text(encoding="utf-8"))
        self.assertEqual(data, {"question": self.request["prompt"], "text": self.request["prompt"]})
        self.assertEqual(result["reviewer"], "codex")

    def test_duplicate_after_restart_never_launches_again(self):
        self.store.submit(self.request)
        fresh = tasks.TaskStore(self.runtime, admitter=lambda *args: self.fail("Duplicate launched core"))
        self.assertTrue(fresh.submit(self.request)["duplicate"])
        self.assertEqual(len(self.calls), 1)

    def test_duplicate_id_with_changed_input_or_writer_is_rejected(self):
        self.store.submit(self.request)
        for change in ({"prompt": "另一个问题"}, {"writer": "claude"}):
            with self.subTest(change=change), self.assertRaises(tasks.TaskError) as error:
                self.store.submit({**self.request, **change})
            self.assertEqual(error.exception.status, 409)
        self.assertEqual(len(self.calls), 1)

    def test_foreign_task_is_not_adopted_or_exposed(self):
        with self.database() as connection:
            connection.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?)", (self.request["id"], "{}", "ACCEPTED", None, "", ""))
        with self.assertRaises(tasks.TaskError) as error:
            self.store.get(self.request["id"])
        self.assertEqual(error.exception.status, 404)
        with self.assertRaises(tasks.TaskError):
            self.store.submit(self.request)
        self.assertEqual(self.calls, [])

    def test_ambiguous_timeout_and_crash_are_not_replayed(self):
        entered = []
        def timeout(argv, started, cwd):
            entered.append(True); started(222, "134369208842965739"); raise tasks.TaskError("CORE_SUBMIT_TIMEOUT", 202)
        store = tasks.TaskStore(self.runtime, admitter=timeout, identity_probe=lambda pid: "UNKNOWN")
        value = store.submit(self.request)
        self.assertEqual(value["state"], "SUBMISSION_UNVERIFIED")
        fresh = tasks.TaskStore(self.runtime, admitter=timeout, identity_probe=lambda pid: "134369208842965739")
        duplicate = fresh.submit(self.request)
        self.assertEqual(duplicate["state"], "SUBMISSION_IN_PROGRESS")
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(len(entered), 1)

    def test_concurrent_retry_has_one_registration(self):
        entered, release = threading.Event(), threading.Event()
        errors = []
        def blocked(argv, started, cwd):
            entered.set(); release.wait(4); return self.admit(argv, started, cwd)
        store = tasks.TaskStore(self.runtime, admitter=blocked)
        def run():
            try: store.submit(self.request)
            except Exception as error: errors.append(error)
        thread = threading.Thread(target=run); thread.start()
        self.assertTrue(entered.wait(3))
        try:
            with self.assertRaises(tasks.TaskError) as error:
                store.submit(self.request)
            self.assertEqual(error.exception.code, "SUBMISSION_IN_PROGRESS")
        finally:
            release.set(); thread.join(5)
        self.assertEqual(errors, [])
        self.assertEqual(len(self.calls), 1)

    def test_input_bounds_exact_keys_types_and_uuid_are_enforced(self):
        bad = [[], {**self.request, "action": "shell"}, {**self.request, "id": "../other"},
               {**self.request, "prompt": ""}, {**self.request, "prompt": "x" * 2001},
               {**self.request, "context": "x" * 12001}, {**self.request, "writer": ["codex"]},
               {**self.request, "context": "中" * 12000}]
        for request in bad:
            with self.subTest(request_type=type(request).__name__), self.assertRaises(tasks.TaskError):
                self.store.submit(request)
        self.assertEqual(self.calls, [])

    def test_core_source_change_disables_admission(self):
        (self.source / "researchops.py").write_text("changed")
        self.assertFalse(self.store.capability()["enabled"])
        with self.assertRaises(tasks.TaskError): self.store.submit(self.request)
        self.assertEqual(self.calls, [])

    def accepted(self):
        self.store.submit(self.request)
        with self.database() as connection:
            spec = json.loads(connection.execute("SELECT spec FROM tasks WHERE id=?", (self.request["id"],)).fetchone()[0])
            connection.execute("UPDATE tasks SET state='ACCEPTED' WHERE id=?", (self.request["id"],))
        artifact = {"task_id": self.request["id"], "input_sha256": spec["input_sha256"], "source_sha256": self.sha,
            "summary": "这是根据给定材料得到的有据可查的限定分析。", "citations": [{"quote": self.request["context"][:6], "start": 0, "end": 6}]}
        binding = tasks.digest(tasks.canonical({"spec": spec, "artifact": artifact}))
        folder = self.runtime / "tasks" / self.request["id"]
        self.write(folder / "artifact.json", artifact)
        self.write(folder / "acceptance.json", {"binding_sha256": binding, "source_sha256": self.sha, "artifact_sha256": tasks.digest(tasks.canonical(artifact))})
        self.write(folder / "review.json", {"review": {"task_id": self.request["id"], "binding_sha256": binding, "verdict": "PASS", "issues": []},
            "evidence": {"exit_code": 0, "tools_disabled": True}, "private_raw": "MUST_NOT_BE_SERVED"})
        return folder

    def test_accepted_result_requires_binding_and_only_final_schema_is_served(self):
        self.accepted()
        before = (self.runtime / "queue.sqlite3").read_bytes()
        value = self.store.get(self.request["id"])
        self.assertEqual(value["result_state"], "ACCEPTED_BOUND_RESULT")
        self.assertEqual(set(value["result"]), {"summary", "citations"})
        self.assertNotIn("MUST_NOT_BE_SERVED", json.dumps(value))
        self.assertNotIn('"input"', json.dumps(value))
        self.assertEqual(before, (self.runtime / "queue.sqlite3").read_bytes())

    def test_wrong_artifact_hash_and_failed_review_never_get_accepted_output(self):
        folder = self.accepted()
        self.write(folder / "acceptance.json", {"artifact_sha256": "f" * 64})
        value = self.store.get(self.request["id"])
        self.assertEqual(value["result_state"], "UNVERIFIED")
        self.assertIsNone(value["result"])

    def test_failed_review_exit_and_wrong_literal_citation_are_rejected(self):
        folder = self.accepted()
        review = json.loads((folder / "review.json").read_text(encoding="utf-8"))
        review["evidence"]["exit_code"] = 1
        self.write(folder / "review.json", review)
        self.assertIsNone(self.store.get(self.request["id"])["result"])
        review["evidence"]["exit_code"] = 0
        artifact = json.loads((folder / "artifact.json").read_text(encoding="utf-8"))
        artifact["citations"][0]["quote"] = "凭空捏造"
        with self.database() as connection:
            spec = json.loads(connection.execute("SELECT spec FROM tasks WHERE id=?", (self.request["id"],)).fetchone()[0])
        binding = tasks.digest(tasks.canonical({"spec": spec, "artifact": artifact}))
        self.write(folder / "artifact.json", artifact)
        self.write(folder / "acceptance.json", {"binding_sha256": binding, "source_sha256": self.sha, "artifact_sha256": tasks.digest(tasks.canonical(artifact))})
        review["review"]["binding_sha256"] = binding; self.write(folder / "review.json", review)
        self.assertIsNone(self.store.get(self.request["id"])["result"])

    def test_real_admitter_timeout_does_not_kill_or_wait_again(self):
        process = Mock(pid=123)
        process.wait.side_effect = tasks.subprocess.TimeoutExpired("fixed", 20)
        started = Mock()
        with patch.object(tasks.subprocess, "Popen", return_value=process), patch.object(tasks, "process_identity", return_value="134369208842965739"):
            with self.assertRaises(tasks.TaskError): tasks.admit(["fixed"], started, self.runtime)
        process.wait.assert_called_once_with(timeout=20)
        process.kill.assert_not_called()
        started.assert_called_once_with(123, "134369208842965739")


if __name__ == "__main__":
    unittest.main()

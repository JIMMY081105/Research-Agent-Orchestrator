"""Research guidance must reach both real stages and reject unregistered bytes."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid

from researchops.analysis_context import analysis_context, FILES
from researchops.integrity import digest, read_json, write_json
from researchops.core import expected
import test_system as baseline


class AnalysisContextTests(unittest.TestCase):
    setUp = baseline.QueueTests.setUp
    tearDown = baseline.QueueTests.tearDown
    fake = baseline.QueueTests.fake
    state = baseline.QueueTests.state

    def test_explicit_repo_copies_match_registry_and_both_origins(self):
        value = analysis_context(self.source)
        self.assertEqual(len(value["skills"]), 2)
        for item in value["skills"]:
            self.assertEqual(item["origin"], FILES[item["file"]])
            self.assertEqual(item["sha256"], digest((self.source/item["file"]).read_bytes()))
        self.assertIn("DRAFT", value["text"])
        self.assertIn("no tools", value["text"])

    def test_changed_skill_rejected_before_admission_and_without_calls(self):
        with (self.source/next(iter(FILES))).open("ab") as stream:
            stream.write(b"\nchanged")
        with self.assertRaises(ValueError):
            self.system.submit(str(uuid.uuid4()), "analyze_text", {"text": "Measured 3.", "question": "What is measured?"})
        self.assertEqual(self.calls, [])
        self.assertEqual(self.system.db.execute("select count(*) from tasks").fetchone()[0], 0)

    def test_unregistered_path_refused_before_any_skill_content_read(self):
        path = self.source/"config/analysis-skill.json"
        value = read_json(path)
        value["files"][0]["file"] = "../auth.json"
        write_json(path, value)
        with patch.object(Path, "read_bytes", side_effect=AssertionError("No skill may be read")):
            with self.assertRaises(ValueError):
                analysis_context(self.source)

    def test_origin_is_metadata_never_an_external_file_read(self):
        seen = []
        original = Path.read_bytes
        def read(path):
            seen.append(path)
            return original(path)
        with patch.object(Path, "read_bytes", read):
            analysis_context(self.source)
        self.assertEqual(set(seen), {self.source/relative for relative in FILES})

    def test_duplicate_missing_foreign_and_wrong_hash_entries_refused(self):
        path = self.source/"config/analysis-skill.json"
        original = read_json(path)
        variants = []
        bad = copy.deepcopy(original); bad["files"][1] = bad["files"][0]; variants.append(bad)
        bad = copy.deepcopy(original); bad["action"] = "execute_shell"; variants.append(bad)
        bad = copy.deepcopy(original); bad["files"][0]["origin"] = "../../../.ssh/id_rsa"; variants.append(bad)
        bad = copy.deepcopy(original); bad["files"][0]["sha256"] = "0"*64; variants.append(bad)
        for bad in variants:
            with self.subTest(bad=bad):
                write_json(path, bad)
                with self.assertRaises(ValueError):
                    analysis_context(self.source)

    def test_writer_and_reviewer_both_receive_source_bound_guidance(self):
        task = str(uuid.uuid4())
        self.system.submit(task, "analyze_text", {"text": "Only one CPU test passed.", "question": "What does this establish?"})
        captured = []
        def fake(*args):
            captured.append(args[3])
            return self.fake(*args)
        self.system.caller = fake
        self.system.tick(); self.system.tick()
        self.assertEqual(self.state(task)["state"], "ACCEPTED")
        self.assertEqual(len(captured), 2)
        for prompt in captured:
            self.assertIn("REGISTERED RESEARCH GUIDANCE", prompt)
            self.assertIn("context-bgv-research-claims-cases.md", prompt)
            self.assertIn("DRAFT", prompt)
        self.assertEqual(self.calls, ["codex", "claude"])

    def span_spec(self):
        text = "HEADER\nfirst measured result\nLABEL\nsecond measured result"
        first, second = text.index("first"), text.index("second")
        data = {"text": text, "question": "Compare these reported results.",
                "source_spans": [[first, first+len("first measured result")], [second, len(text)]]}
        task = str(uuid.uuid4())
        self.system.submit(task, "analyze_text", data)
        import json
        spec = json.loads(self.state(task)["spec"])
        artifact = {"task_id": task, "input_sha256": spec["input_sha256"],
                    "source_sha256": spec["source"]["sha256"], "summary": "The supplied results differ.",
                    "citations": [{"quote": "first measured result", "start": first,
                                   "end": first+len("first measured result")}]}
        return spec, artifact

    def test_body_quote_passes_but_exact_header_and_cross_source_quotes_fail(self):
        spec, artifact = self.span_spec()
        self.assertTrue(self.system.valid_artifact(spec, artifact))
        artifact["citations"] = [{"quote": "HEADER", "start": 0, "end": 6}]
        self.assertFalse(self.system.valid_artifact(spec, artifact))
        text = spec["input"]["text"]
        start, end = spec["input"]["source_spans"][0][0], len(text)
        artifact["citations"] = [{"quote": text[start:end], "start": start, "end": end}]
        self.assertFalse(self.system.valid_artifact(spec, artifact))

    def test_invalid_body_spans_rejected_before_admission(self):
        for spans in ([], [[False, 2]], [[0, 4]], [[2, 1]], [[0.0, 1]],
                      [[0, 2], [1, 3]], [[2, 3], [0, 1]], [[-1, 2]], [[0, 1, 2]],
                      [[0, 1]]*9, "0..2"):
            with self.subTest(spans=spans):
                with self.assertRaises(ValueError):
                    expected("analyze_text", {"text": "abc", "question": "Which claims?", "source_spans": spans})

    def test_execution_example_is_a_body_quote_and_acceptance_respects_it(self):
        spec, _ = self.span_spec()
        captured = []
        def fake(*args):
            captured.append(args[3])
            value, meta = self.fake(*args)
            if "TASK DATA\n" in args[3]:
                import json
                data = json.loads(args[3].split("TASK DATA\n", 1)[1])
                value["citations"] = [data["citation_example"]]
            return value, meta
        self.system.caller = fake
        self.system.tick(); self.system.tick()
        self.assertEqual(self.state(spec["id"])["state"], "ACCEPTED")
        self.assertEqual(len(captured), 2)

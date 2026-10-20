"""Independent UI hash and installation gates can reject stale/modified content."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from researchops import dashboard_bundle as b


class DashboardBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        approved = {name: b.digest(b"fixture image") for name in b.AVATARS}
        self.avatar_patch = patch.object(b, "AVATARS", approved)
        self.avatar_patch.start(); self.addCleanup(self.avatar_patch.stop)
        self.root = self.base / "source"; self.root.mkdir()
        for name in b.FILES:
            file = self.root / name; file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("fixture source\n", encoding="utf-8")
        self.config = {"owner": b.OWNER, "bind": "127.0.0.1", "port": 8765,
                       "ssh": r"C:\Windows\System32\OpenSSH\ssh.exe", "ssh_alias": "sunmingyuan1",
                       "state_poll_seconds": 2, "gpu_poll_seconds": 30, "gpu_stale_seconds": 90}
        self.bundle = self.base / "snapshot"; self.bundle.mkdir()
        self.frozen = self.bundle / "source"; self.frozen.mkdir()
        for name in b.FILES:
            path = self.frozen / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((self.root / name).read_bytes())
        (self.frozen / "config/live.json").write_bytes(b.canonical(self.config))
        (self.frozen / "assets").mkdir()
        for name in b.AVATARS:
            (self.frozen / "assets" / name).write_bytes(b"fixture image")
        files = {p.relative_to(self.frozen).as_posix(): b.digest(p.read_bytes())
                 for p in self.frozen.rglob("*") if p.is_file()}
        self.record = {"owner": b.OWNER, "files": files, "sha256": b.digest(b.canonical(files)),
                       "source_sha256": b.source_manifest(self.root)["sha256"]}
        self.write_manifest()
    def tearDown(self): self.temp.cleanup()
    def write_manifest(self):
        (self.bundle / "manifest.json").write_bytes(b.canonical(self.record))
    def test_unchanged_complete_snapshot_verifies(self):
        self.assertEqual(b.verify(self.bundle, self.record["sha256"]), self.record)
    def test_source_edit_without_commit_is_rejected(self):
        (self.frozen / "researchops/dashboard_web.py").write_text("modified")
        with self.assertRaisesRegex(ValueError, "CONTENT_CHANGED"):
            b.verify(self.bundle, self.record["sha256"])
    def test_configuration_edit_is_rejected(self):
        (self.frozen / "config/live.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "CONTENT_CHANGED"):
            b.verify(self.bundle, self.record["sha256"])
    def test_avatar_edit_is_rejected(self):
        (self.frozen / "assets/lucy.jpg").write_bytes(b"wrong face")
        with self.assertRaisesRegex(ValueError, "CONTENT_CHANGED"):
            b.verify(self.bundle, self.record["sha256"])
    def test_extra_source_file_is_rejected(self):
        (self.frozen / "extra.py").write_text("unexpected")
        with self.assertRaisesRegex(ValueError, "FILESET_CHANGED"):
            b.verify(self.bundle, self.record["sha256"])
    def test_forged_manifest_with_old_expected_hash_fails(self):
        self.record["files"]["dashboard.py"] = "0" * 64; self.write_manifest()
        with self.assertRaisesRegex(ValueError, "MANIFEST_INVALID"):
            b.verify(self.bundle, self.record["sha256"])
    def test_missing_hash_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "HASH_REQUIRED"):
            b.verify(self.bundle, "")
    def test_unknown_config_keys_and_remote_bind_rejected(self):
        for modified in ({**self.config, "token": "never-accepted"}, {**self.config, "bind": "0.0.0.0"}):
            with self.assertRaises(ValueError): b.validate_config(modified)
    def test_arbitrary_ssh_command_rejected(self):
        for changed in ({**self.config, "ssh_alias": "-oProxyCommand=cmd"}, {**self.config, "ssh": "cmd.exe"}):
            with self.assertRaises(ValueError): b.validate_config(changed)
    def test_fresh_ui_content_changes_source_manifest(self):
        old = b.source_manifest(self.root)
        (self.root / "researchops/dashboard_state.py").write_text("new state projection")
        self.assertNotEqual(old["sha256"], b.source_manifest(self.root)["sha256"])
    def test_freeze_rejects_stale_or_incomplete_test_evidence(self):
        runtime = self.base / "runtime"; runtime.mkdir()
        tests = self.base / "tests.json"; review = self.base / "review.json"
        review.write_text("{}")
        for evidence in (
            {"source_sha256": "old", "success": True, "tests_run": 62, "discovered": 62},
            {"source_sha256": self.record["source_sha256"], "success": True, "tests_run": 62, "discovered": 63},
            {"source_sha256": self.record["source_sha256"], "success": False, "tests_run": 62, "discovered": 62},
        ):
            tests.write_text(json.dumps(evidence))
            with patch.object(b, "bundle_manifest", return_value=self.record):
                with self.assertRaisesRegex(ValueError, "CURRENT_UI_TESTS_REQUIRED"):
                    b.freeze(self.root, runtime, self.config, self.frozen / "assets", tests, review)
        self.assertFalse((runtime / "dashboard/snapshots").exists())
    def test_freeze_rejects_old_review_or_changed_live_configuration(self):
        runtime = self.base / "runtime"; runtime.mkdir()
        tests = self.base / "tests.json"; review = self.base / "review.json"
        tests.write_text(json.dumps({"source_sha256": self.record["source_sha256"], "success": True,
                                     "tests_run": 62, "discovered": 62}))
        proof = {"source_sha256": self.record["source_sha256"], "bundle_sha256": "old-config",
                 "tests_sha256": b.digest(tests.read_bytes()), "verdict": "PASS", "issues": [],
                 "tools_disabled": True, "call_id": "fixture", "session_id": "fixture"}
        review.write_text(json.dumps(proof))
        with patch.object(b, "bundle_manifest", return_value=self.record):
            with self.assertRaisesRegex(ValueError, "CURRENT_INDEPENDENT_UI_REVIEW_REQUIRED"):
                b.freeze(self.root, runtime, self.config, self.frozen / "assets", tests, review)
        self.assertFalse((runtime / "dashboard/snapshots").exists())


if __name__ == "__main__": unittest.main()

"""Desktop snapshots reject stale evidence, altered binaries and unrelated files."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from researchops import dashboard_bundle as dashboard
from researchops import desktop_bundle as bundle


FIXTURE_SOURCES = bundle.BUILD_INPUTS + ("desktop.py", "researchops/desktop_bundle.py")


class DesktopBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "repo"
        self.root.mkdir()
        self.runtime = self.root / ".runtime"
        self.runtime.mkdir()
        self.assets = self.runtime / "approved-assets"
        self.assets.mkdir()
        self.app = self.runtime / "build/app"
        self.app.mkdir(parents=True)
        self.build_path = self.runtime / "build/build.json"
        self.tests_path = self.runtime / "tests.json"
        self.review_path = self.runtime / "review.json"
        patcher = patch.object(bundle, "SOURCE_FILES", FIXTURE_SOURCES)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in FIXTURE_SOURCES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture source " + name)
        for name in bundle.APP_FILES:
            (self.app / name).write_bytes(b"MZ fixture " + name.encode())
        self.dependencies = {"package": "Microsoft.Web.WebView2", "version": "1.0.3595.46",
                             "url": "https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/fixture.nupkg",
                             "sha256": "a" * 64,
                             "files": {name: bundle.digest((self.app / name).read_bytes())
                                       for name in bundle.DEPENDENCY_FILES}}
        self.write_dependencies()
        data = b"\xff\xd8\xff approved test image"
        avatar_patch = patch.object(dashboard, "AVATARS", {name: bundle.digest(data) for name in dashboard.AVATARS})
        avatar_patch.start()
        self.addCleanup(avatar_patch.stop)
        for name in dashboard.AVATARS:
            (self.assets / name).write_bytes(data)
        clip = b"\x00\x00\x00\x18ftypisom approved video"
        video_patch = patch.object(dashboard, "AVATAR_VIDEOS", {name: bundle.digest(clip) for name in dashboard.AVATAR_VIDEOS})
        video_patch.start(); self.addCleanup(video_patch.stop)
        for name in dashboard.AVATAR_VIDEOS:
            (self.assets / name).write_bytes(clip)
        self.config = {"owner": dashboard.OWNER, "bind": "127.0.0.1", "port": 8765,
                       "ssh": r"C:\Windows\System32\OpenSSH\ssh.exe", "ssh_alias": "sunmingyuan1",
                       "state_poll_seconds": 2, "gpu_poll_seconds": 30, "gpu_stale_seconds": 90}
        self.refresh_build()
        self.refresh_evidence()

    def write_dependencies(self):
        (self.root / "config/desktop-dependencies.json").write_bytes(bundle.canonical(self.dependencies))

    def refresh_build(self):
        sources = bundle.source_manifest(self.root)
        self.build = {"success": True,
                      "source_inputs": {name: sources["files"][name] for name in bundle.BUILD_INPUTS},
                      "app_files": {name: bundle.digest((self.app / name).read_bytes()) for name in bundle.APP_FILES},
                      "compiler": {"path": r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
                                   "sha256": "b" * 64, "version": "4.8 fixture compiler"}}
        self.write_build()

    def write_build(self):
        self.build_path.write_bytes(bundle.canonical(self.build))

    def packed(self):
        return bundle.bundle_manifest(self.root, self.config, self.assets, self.app, self.build_path)

    def refresh_evidence(self):
        record = self.packed()
        self.tests = {"success": True, "source_unchanged": True, "source_sha256": record["source_sha256"],
                      "discovered": 64, "tests_run": 64, "errors": [], "failures": [], "skipped": []}
        self.tests_path.write_bytes(bundle.canonical(self.tests))
        self.review = {"owner": bundle.OWNER, "source_sha256": record["source_sha256"],
                       "bundle_sha256": record["sha256"], "tests_sha256": bundle.digest(self.tests_path.read_bytes()),
                       "verdict": "PASS", "issues": [], "tools_disabled": True,
                       "session_id": "desktop-fixture-session", "call_id": "desktop-fixture-call"}
        self.review_path.write_bytes(bundle.canonical(self.review))

    def freeze(self):
        return bundle.freeze(self.root, self.runtime, self.config, self.assets, self.app,
                             self.build_path, self.tests_path, self.review_path)

    def rewrite_record(self, directory, record):
        record["sha256"] = bundle.digest(bundle.canonical(record["files"]))
        (directory / "manifest.json").write_bytes(bundle.canonical(record))
        return record["sha256"]

    def test_complete_snapshot_contains_actual_source_config_assets_app_and_build(self):
        record, target = self.freeze()
        self.assertEqual(self.runtime / "desktop/snapshots" / record["sha256"], target)
        self.assertEqual(record, bundle.verify(target, record["sha256"]))
        expected = {"source/" + name for name in FIXTURE_SOURCES} | {"source/config/live.json", "build.json"}
        expected.update("source/assets/" + name for name in (*dashboard.AVATARS, *dashboard.AVATAR_VIDEOS))
        expected.update("app/" + name for name in bundle.APP_FILES)
        self.assertEqual(expected, set(record["files"]))
        self.assertNotIn("manifest.json", record["files"])
        self.assertEqual(bundle.source_manifest(self.root)["sha256"], record["source_sha256"])

    def test_repeat_freeze_verifies_and_reuses_same_immutable_snapshot(self):
        first = self.freeze()
        second = self.freeze()
        self.assertEqual(first, second)
        self.assertFalse(any((self.runtime / "desktop").glob(".staging-*")))

    def test_arbitrary_runtime_cannot_be_used(self):
        with self.assertRaisesRegex(ValueError, "RUNTIME_BOUNDARY"):
            bundle.freeze(self.root, self.base / "other-system", self.config, self.assets, self.app,
                          self.build_path, self.tests_path, self.review_path)
        self.assertFalse((self.base / "other-system").exists())

    def test_source_edit_invalidates_tests_and_review_without_relying_on_git_head(self):
        (self.root / "desktop.py").write_text("new code after tests")
        with self.assertRaisesRegex(ValueError, "CURRENT_DESKTOP_TESTS"):
            self.freeze()

    def test_all_executed_source_paths_must_be_safe_and_present(self):
        with patch.object(bundle, "SOURCE_FILES", FIXTURE_SOURCES + ("../unknown.py",)):
            with self.assertRaisesRegex(ValueError, "UNSAFE_RELATIVE"):
                bundle.source_manifest(self.root)
        (self.root / "desktop.py").unlink()
        with self.assertRaisesRegex(ValueError, "MISSING_OR_TOO_LARGE"):
            bundle.source_manifest(self.root)

    def test_changed_live_config_requires_new_review(self):
        self.config["port"] = 8766
        with self.assertRaisesRegex(ValueError, "CURRENT_INDEPENDENT_DESKTOP_REVIEW"):
            self.freeze()

    def test_config_cannot_expand_permissions_or_bind_to_external_network(self):
        for invalid in ({**self.config, "bind": "0.0.0.0"}, {**self.config, "arbitrary_command": "x"}):
            with self.assertRaises(ValueError):
                bundle.bundle_manifest(self.root, invalid, self.assets, self.app, self.build_path)

    def test_missing_or_modified_avatar_is_rejected(self):
        (self.assets / "lucy.jpg").write_bytes(b"\xff\xd8\xff unapproved")
        with self.assertRaisesRegex(ValueError, "UNAPPROVED_AVATAR"):
            self.packed()

    def test_changed_app_binary_or_build_input_is_rejected_before_evidence_gates(self):
        (self.app / "SceneControl.exe").write_bytes(b"MZ different binary")
        with self.assertRaisesRegex(ValueError, "BUILD_BINDING_INVALID"):
            self.packed()
        self.refresh_build()
        (self.root / "native/SceneControl.cs").write_text("changed native code")
        with self.assertRaisesRegex(ValueError, "BUILD_BINDING_INVALID"):
            self.packed()

    def test_dependency_pins_must_match_dll_bytes_even_with_new_build_hashes(self):
        (self.app / "WebView2Loader.dll").write_bytes(b"MZ not pinned")
        self.refresh_build()
        with self.assertRaisesRegex(ValueError, "DEPENDENCY_HASH_MISMATCH"):
            self.packed()

    def test_dependency_config_rejects_missing_hashes_extra_dlls_and_insecure_url(self):
        original = copy.deepcopy(self.dependencies)
        for change in ("extra", "missing", "url", "package"):
            self.dependencies = copy.deepcopy(original)
            if change == "extra":
                self.dependencies["files"]["unknown.dll"] = "a" * 64
            elif change == "missing":
                self.dependencies["files"].pop("WebView2Loader.dll")
            elif change == "url":
                self.dependencies["url"] = "http://example.invalid/package"
            else:
                self.dependencies["package"] = "Unknown.Package"
            self.write_dependencies()
            with self.assertRaisesRegex(ValueError, "DEPENDENCIES_INVALID"):
                self.packed()

    def test_build_requires_success_complete_input_and_compiler_evidence(self):
        original = copy.deepcopy(self.build)
        changes = [lambda d: d.update(success=False), lambda d: d["source_inputs"].pop("tools/build_desktop.py"),
                   lambda d: d["app_files"].update({"extra.dll": "a" * 64}),
                   lambda d: d.update(compiler={}), lambda d: d["compiler"].update(path="csc.exe"),
                   lambda d: d["compiler"].update(sha256="not-a-hash")]
        for change in changes:
            self.build = copy.deepcopy(original)
            change(self.build)
            self.write_build()
            with self.assertRaises(ValueError):
                self.packed()

    def test_full_current_test_run_is_mandatory_no_skips_no_old_hash(self):
        original = copy.deepcopy(self.tests)
        changes = [{"source_sha256": "a" * 64}, {"source_unchanged": False}, {"success": False},
                   {"tests_run": 63, "discovered": 63}, {"tests_run": 64, "discovered": 65},
                   {"tests_run": True}, {"failures": ["failure"]}, {"errors": ["error"]}, {"skipped": ["skip"]}]
        for change in changes:
            self.tests_path.write_bytes(bundle.canonical({**original, **change}))
            with self.assertRaisesRegex(ValueError, "CURRENT_DESKTOP_TESTS_REQUIRED"):
                self.freeze()
        del original["skipped"]
        self.tests_path.write_bytes(bundle.canonical(original))
        with self.assertRaisesRegex(ValueError, "CURRENT_DESKTOP_TESTS_REQUIRED"):
            self.freeze()
        self.assertFalse((self.runtime / "desktop").exists())

    def test_fresh_desktop_review_required_not_previous_ui_review_or_edited_test_evidence(self):
        for change in ({"owner": dashboard.OWNER}, {"source_sha256": "a" * 64},
                       {"bundle_sha256": "b" * 64}, {"tests_sha256": "c" * 64},
                       {"tools_disabled": False}, {"verdict": "REWORK"}, {"issues": ["remaining defect"]},
                       {"session_id": ""}, {"call_id": None}):
            self.review_path.write_bytes(bundle.canonical({**self.review, **change}))
            with self.assertRaisesRegex(ValueError, "CURRENT_INDEPENDENT_DESKTOP_REVIEW_REQUIRED"):
                self.freeze()
        self.review_path.write_bytes(bundle.canonical(self.review))
        self.tests_path.write_bytes(self.tests_path.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "CURRENT_INDEPENDENT_DESKTOP_REVIEW_REQUIRED"):
            self.freeze()

    def test_snapshot_source_configuration_avatar_build_and_binary_drift_all_fail(self):
        for relative in ("source/desktop.py", "source/config/live.json", "source/assets/david.jpg",
                         "app/SceneControl.exe", "app/WebView2Loader.dll", "build.json"):
            record, target = self.freeze()
            path = target / relative
            original = path.read_bytes()
            path.write_bytes(original + b" tampered")
            with self.assertRaisesRegex(ValueError, "CONTENT_CHANGED"):
                bundle.verify(target, record["sha256"])
            path.write_bytes(original)

    def test_extra_files_and_even_unexpected_empty_directories_are_rejected(self):
        record, target = self.freeze()
        for relative in ("extra.txt", "source/researchops/unknown.py", "app/extra.dll", "source/__pycache__/extra.pyc"):
            path = target / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("extra")
            with self.assertRaisesRegex(ValueError, "FILESET_CHANGED"):
                bundle.verify(target, record["sha256"])
            path.unlink()
            if path.parent.name == "__pycache__":
                path.parent.rmdir()
        (target / "unrelated-empty-dir").mkdir()
        with self.assertRaisesRegex(ValueError, "FILESET_CHANGED"):
            bundle.verify(target, record["sha256"])

    def test_missing_snapshot_file_and_wrong_expected_hash_are_rejected(self):
        record, target = self.freeze()
        with self.assertRaisesRegex(ValueError, "HASH_REQUIRED"):
            bundle.verify(target, "")
        with self.assertRaisesRegex(ValueError, "MANIFEST_INVALID"):
            bundle.verify(target, "0" * 64)
        (target / "app/SceneControl.ico").unlink()
        with self.assertRaisesRegex(ValueError, "FILESET_CHANGED"):
            bundle.verify(target, record["sha256"])

    def test_rehashed_binary_tampering_still_fails_build_binding(self):
        record, target = self.freeze()
        (target / "app/SceneControl.exe").write_bytes(b"MZ forged exe")
        record["files"]["app/SceneControl.exe"] = bundle.digest((target / "app/SceneControl.exe").read_bytes())
        expected = self.rewrite_record(target, record)
        with self.assertRaisesRegex(ValueError, "BUILD_BINDING_INVALID"):
            bundle.verify(target, expected)

    def test_rehashed_native_source_tampering_still_fails_build_input_binding(self):
        record, target = self.freeze()
        relative = "source/native/SceneControl.cs"
        (target / relative).write_text("changed native source")
        record["files"][relative] = bundle.digest((target / relative).read_bytes())
        record["source_sha256"] = bundle.digest(bundle.canonical({name: record["files"]["source/" + name] for name in FIXTURE_SOURCES}))
        expected = self.rewrite_record(target, record)
        with self.assertRaisesRegex(ValueError, "BUILD_BINDING_INVALID"):
            bundle.verify(target, expected)

    def test_existing_unknown_staging_is_preserved_and_not_reused(self):
        record = self.packed()
        stage = self.runtime / "desktop" / (".staging-" + record["sha256"])
        stage.mkdir(parents=True)
        sentinel = stage / "unknown-data.txt"
        sentinel.write_text("must not overwrite/delete")
        with self.assertRaisesRegex(ValueError, "STAGING_EXISTS_RETAINED"):
            self.freeze()
        self.assertEqual("must not overwrite/delete", sentinel.read_text())

    def test_copy_time_source_change_never_promotes_partial_snapshot(self):
        real_copy = bundle.shutil.copyfile
        changed = False
        def mutating_copy(source, target):
            nonlocal changed
            result = real_copy(source, target)
            if not changed:
                changed = True
                (self.root / "desktop.py").write_text("changed while freezing")
            return result
        with patch.object(bundle.shutil, "copyfile", side_effect=mutating_copy):
            with self.assertRaises(ValueError):
                self.freeze()
        self.assertFalse((self.runtime / "desktop/snapshots").exists())
        self.assertTrue(any((self.runtime / "desktop").glob(".staging-*")))

    def test_reparse_path_is_rejected_before_inventory_descends(self):
        record, target = self.freeze()
        outside = self.runtime / "unrelated-fixture-data"
        outside.mkdir()
        sentinel = outside / "must-not-read-or-delete.txt"
        sentinel.write_text("unrelated data preserved")
        link = target / "source" / "linked-fixture"
        if sys.platform == "win32":
            import _winapi
            _winapi.CreateJunction(str(outside), str(link))
        else:
            link.symlink_to(outside, target_is_directory=True)
        try:
            with self.assertRaisesRegex(ValueError, "REPARSE_PATH"):
                bundle.verify(target, record["sha256"])
            self.assertEqual("unrelated data preserved", sentinel.read_text())
        finally:
            if sys.platform == "win32":
                link.rmdir()  # Remove only the junction created above, never its target.
            else:
                link.unlink()


if __name__ == "__main__":
    unittest.main()

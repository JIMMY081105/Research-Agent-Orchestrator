import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
import uuid

from researchops import github_review as b

ROOT = Path(__file__).parents[1]
BASE = "a" * 40
TREE = "b" * 40


class FakeApi:
    def __init__(self):
        self.calls = []
        self.branches = {}
        self.pulls = []
        self.private = True
        self.allow_push = True
        self.repo_name = b.REPOSITORY
        self.fail = None
        self.lose = None
        self.collide = False
        self.trees = {}
        self.commits = {}
        self.bad_commit = False

    def request(self, method, endpoint, payload=None, missing=False):
        self.calls.append((method, endpoint, payload))
        route = endpoint.removeprefix("repos/" + b.REPOSITORY)
        if method == "GET":
            if not route:
                return {"full_name": self.repo_name, "private": self.private, "archived": False,
                        "permissions": {"push": self.allow_push}, "default_branch": "main"}
            if route == "/git/ref/heads/main":
                return {"object": {"sha": BASE, "type": "commit"}}
            if route == "/git/commits/" + BASE:
                return {"tree": {"sha": TREE}}
            if route.startswith("/git/ref/heads/"):
                name = route.removeprefix("/git/ref/heads/")
                return {"object": {"sha": self.branches[name], "type": "commit"}} if name in self.branches else None
            if route.startswith("/contents/"):
                return [] if self.collide else None
            if route.startswith("/pulls?"):
                return list(self.pulls)
            if route.startswith("/commits/"):
                result = self.commits[route.removeprefix("/commits/")]
                if self.bad_commit:
                    return {**result, "files": [{"filename": "stolen.json", "sha": "f" * 40, "status": "added"}]}
                return result
            raise AssertionError(route)
        if self.fail == route:
            raise b.BridgeError("GITHUB_TIMEOUT")
        sha = hashlib.sha1(b.canonical(payload)).hexdigest()
        result = {"sha": sha}
        if route == "/git/blobs":
            result = {"sha": b.git_blob_sha(__import__("base64").b64decode(payload["content"]))}
        elif route == "/git/trees":
            self.trees[sha] = payload["tree"]
        elif route == "/git/commits":
            self.commits[sha] = {"sha": sha, "parents": [{"sha": p} for p in payload["parents"]],
                                 "files": [{"filename": f["path"], "sha": f["sha"], "status": "added"}
                                           for f in self.trees[payload["tree"]]]}
        elif route == "/git/refs":
            branch = payload["ref"].removeprefix("refs/heads/")
            if branch in self.branches:
                raise b.BridgeError("GITHUB_CONFLICT")
            self.branches[branch] = payload["sha"]
            result = {"object": {"sha": payload["sha"]}}
        elif route == "/pulls":
            self.pulls.append({"number": 17, "html_url": "https://github.com/" + b.REPOSITORY + "/pull/17",
                               "head": {"ref": payload["head"], "sha": self.branches[payload["head"]],
                                        "repo": {"full_name": b.REPOSITORY}},
                               "base": {"ref": payload["base"], "repo": {"full_name": b.REPOSITORY}},
                               "draft": payload["draft"], "state": "open", "merged_at": None})
            result = self.pulls[-1]
        if self.lose == route:
            raise b.BridgeError("GITHUB_TIMEOUT")
        return result


class ReviewBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.runtime = self.repo / ".runtime/github"
        self.api = FakeApi()
        self.app = b.Bridge(self.repo, self.runtime, ROOT, self.api)
        self.ident = str(uuid.uuid4())
        self.local_check = mock.patch.object(b, "verify_repository", return_value=self.repo)
        self.local_check.start(); self.addCleanup(self.local_check.stop)
        self.release = mock.patch.object(self.app, "verify_release")
        self.release.start(); self.addCleanup(self.release.stop)
        self.intake = self.app.directory(self.ident, "intake")
        self.intake.mkdir(parents=True)
        self.body = b"# Result\nThree controls are pending. No experiments were started.\n"
        (self.intake / "REPORT.md").write_bytes(self.body)
        self.request = {"schema": 1, "id": self.ident, "title": "Factory80 review", "summary": "Delivery test only.",
                        "reported_status": "UNVERIFIED", "files": [{"path": "REPORT.md", "sha256": b.digest(self.body)}]}
        self.write_request()

    def write_request(self):
        b.save(self.intake / "ready.json", self.request)

    def prepared(self):
        return self.app.prepare(self.ident)

    def publish(self, receipt=None):
        receipt = receipt or self.prepared()
        return self.app.publish(self.ident, receipt["sha256"], True)

    def posts(self):
        return [x for x in self.api.calls if x[0] == "POST"]

    def test_prepare_is_remote_read_only_and_frozen(self):
        value = self.prepared()
        self.assertEqual(value["state"], "PREPARED_NOT_PUBLISHED")
        self.assertFalse(self.posts())
        self.assertEqual((self.app.directory(self.ident) / "files/REPORT.md").read_bytes(), self.body)
        self.assertIn("not scientific correctness", (self.app.directory(self.ident) / "PREVIEW.md").read_text())

    def test_publish_creates_exact_prefix_branch_and_draft(self):
        result = self.publish()
        self.assertEqual(result["state"], "PUBLISHED_DRAFT")
        self.assertEqual(self.api.pulls[0]["head"]["ref"], "bgv/review/" + self.ident)
        tree = next(x[2] for x in self.posts() if x[1].endswith("/git/trees"))
        self.assertEqual(tree["base_tree"], TREE)
        self.assertTrue(all(x["path"].startswith("reviews/" + self.ident + "/") for x in tree["tree"]))
        self.assertEqual({x["path"].split("/")[-1] for x in tree["tree"]}, {"README.md", "REPORT.md", "delivery-manifest.json"})
        self.assertFalse(any("merge" in x[1] or x[0] not in ("GET", "POST") for x in self.api.calls))

    def test_repeat_returns_same_pr_without_more_writes(self):
        receipt = self.prepared()
        first = self.publish(receipt)
        count = len(self.posts())
        second = self.publish(receipt)
        self.assertEqual(first["url"], second["url"])
        self.assertEqual(len(self.posts()), count)

    def test_no_implicit_publication(self):
        receipt = self.prepared()
        with self.assertRaisesRegex(b.BridgeError, "AUTHORIZATION_REQUIRED"):
            self.app.publish(self.ident, receipt["sha256"])
        self.assertFalse(self.posts())

    def test_wrong_expected_package_rejected(self):
        self.prepared()
        with self.assertRaisesRegex(b.BridgeError, "PACKAGE_OR_SOURCE_CHANGED"):
            self.app.publish(self.ident, "0" * 64, True)
        self.assertFalse(self.posts())

    def test_source_input_change_rejects_old_package(self):
        receipt = self.prepared()
        (self.intake / "REPORT.md").write_bytes(b"changed")
        with self.assertRaisesRegex(b.BridgeError, "ARTIFACT_CHANGED"):
            self.publish(receipt)
        self.assertFalse(self.posts())

    def test_copied_artifact_change_rejected(self):
        receipt = self.prepared()
        (self.app.directory(self.ident) / "files/REPORT.md").write_bytes(b"changed")
        with self.assertRaisesRegex(b.BridgeError, "ARTIFACT_CHANGED"):
            self.publish(receipt)

    def test_request_change_rejected(self):
        receipt = self.prepared()
        self.request["summary"] = "different"; self.write_request()
        with self.assertRaisesRegex(b.BridgeError, "SOURCE_REQUEST_CHANGED"):
            self.publish(receipt)

    def test_code_change_rejected(self):
        receipt = self.prepared()
        source = b.manifest(ROOT)
        with mock.patch.object(b, "manifest", return_value={**source, "sha256": "0" * 64}):
            with self.assertRaisesRegex(b.BridgeError, "PACKAGE_OR_SOURCE_CHANGED"):
                self.publish(receipt)

    def test_duplicate_prepare_does_not_overwrite(self):
        receipt = self.prepared()
        before = (self.app.directory(self.ident) / "package.json").read_bytes()
        with self.assertRaises(FileExistsError):
            self.prepared()
        self.assertEqual(before, (self.app.directory(self.ident) / "package.json").read_bytes())
        self.app.package(self.ident, receipt["sha256"])

    def test_wrong_hash_on_input_rejected(self):
        self.request["files"][0]["sha256"] = "0" * 64; self.write_request()
        with self.assertRaisesRegex(b.BridgeError, "INPUT_HASH_MISMATCH"):
            self.prepared()

    def test_paths_reject_traversal_absolute_scripts_and_secrets(self):
        for name in ("../REPORT.md", "/REPORT.md", "C:/REPORT.md", "a\\REPORT.md", ".runtime/x.json",
                     "credentials/x.json", "raw-output.json", "machine.json", "run.ps1", "NUL.md", "a//b.json"):
            with self.subTest(name=name), self.assertRaises(b.BridgeError):
                b.relative(name)

    def test_reparse_path_rejected(self):
        with mock.patch.object(Path, "is_junction", return_value=True):
            with self.assertRaisesRegex(b.BridgeError, "REPARSE_PATH"):
                b.read(self.intake / "REPORT.md")

    def test_credential_signature_rejected(self):
        self.body = ("ghp_" + "A" * 32).encode()
        (self.intake / "REPORT.md").write_bytes(self.body)
        self.request["files"][0]["sha256"] = b.digest(self.body); self.write_request()
        with self.assertRaisesRegex(b.BridgeError, "SENSITIVE_ARTIFACT"):
            self.prepared()

    def test_sensitive_summary_rejected(self):
        self.request["summary"] = "sk-" + "B" * 40; self.write_request()
        with self.assertRaisesRegex(b.BridgeError, "SENSITIVE_TEXT"):
            self.prepared()

    def test_case_alias_rejected(self):
        self.request["files"].append({"path": "report.md", "sha256": b.digest(self.body)})
        self.write_request()
        with self.assertRaisesRegex(b.BridgeError, "DUPLICATE_OR_RESERVED_PATH"):
            self.prepared()

    def test_reserved_generated_path_rejected(self):
        self.request["files"][0]["path"] = "README.md"; self.write_request()
        with self.assertRaisesRegex(b.BridgeError, "DUPLICATE_OR_RESERVED_PATH"):
            self.prepared()

    def test_private_target_is_required(self):
        self.api.private = False
        with self.assertRaisesRegex(b.BridgeError, "PRIVATE_TARGET"):
            self.prepared()
        self.assertFalse(self.posts())

    def test_other_repository_rejected(self):
        self.api.repo_name = "JIMMY081105/Buildings-Generation"
        with self.assertRaisesRegex(b.BridgeError, "PRIVATE_TARGET"):
            self.prepared()

    def test_write_permission_required(self):
        self.api.allow_push = False
        with self.assertRaisesRegex(b.BridgeError, "PERMISSION_MISMATCH"):
            self.prepared()

    def test_missing_or_changed_local_origin_blocks_connection(self):
        self.local_check.stop()
        wrong = subprocess.CompletedProcess([], 0, b"wrong-repository\n", b"")
        with mock.patch.object(subprocess, "run", return_value=wrong):
            with self.assertRaisesRegex(b.BridgeError, "IDENTITY_MISMATCH"):
                self.app.connection()
        self.local_check.start()

    def test_existing_unowned_branch_never_overwritten(self):
        receipt = self.prepared()
        self.api.branches["bgv/review/" + self.ident] = "c" * 40
        with self.assertRaisesRegex(b.BridgeError, "EXISTING_BRANCH_NOT_OWNED"):
            self.publish(receipt)
        self.assertFalse(self.posts())

    def test_existing_prefix_never_overwritten(self):
        receipt = self.prepared(); self.api.collide = True
        with self.assertRaisesRegex(b.BridgeError, "RESULT_PREFIX_ALREADY_EXISTS"):
            self.publish(receipt)
        self.assertFalse(self.posts())

    def test_uncertain_write_stays_paused_no_retry(self):
        receipt = self.prepared(); self.api.fail = "/pulls"
        with self.assertRaisesRegex(b.BridgeError, "GITHUB_TIMEOUT"):
            self.publish(receipt)
        count = len(self.posts())
        with self.assertRaisesRegex(b.BridgeError, "RECONCILE_REQUIRED"):
            self.publish(receipt)
        self.app.reconcile(self.ident, receipt["sha256"])
        self.assertEqual(count, len(self.posts()))
        self.assertEqual(b.load(self.app.directory(self.ident) / "state.json")["state"], "NEEDS_RECONCILIATION")

    def test_lost_pr_receipt_reconciles_without_duplicate(self):
        receipt = self.prepared(); self.api.lose = "/pulls"
        with self.assertRaises(b.BridgeError):
            self.publish(receipt)
        count = len(self.posts())
        state = self.app.reconcile(self.ident, receipt["sha256"])
        self.assertEqual(state["state"], "PUBLISHED_DRAFT")
        self.assertEqual(len(self.posts()), count)

    def test_lost_branch_receipt_can_be_confirmed_read_only(self):
        receipt = self.prepared(); self.api.lose = "/git/refs"
        with self.assertRaises(b.BridgeError):
            self.publish(receipt)
        count = len(self.posts())
        state = self.app.reconcile(self.ident, receipt["sha256"])
        self.assertEqual(state["state"], "BRANCH_CREATED")
        self.assertEqual(len(self.posts()), count)
        self.api.lose = None
        self.assertEqual(self.publish(receipt)["state"], "PUBLISHED_DRAFT")
        self.assertEqual(len(self.api.branches), 1)

    def test_merged_pr_does_not_trigger_another_pr(self):
        receipt = self.prepared(); self.publish(receipt)
        self.api.pulls[0]["merged_at"] = b.now(); self.api.pulls[0]["state"] = "closed"
        count = len(self.posts())
        self.assertEqual(self.publish(receipt)["state"], "MERGED_BY_USER")
        self.assertEqual(len(self.posts()), count)

    def test_cross_repo_pr_readback_rejected(self):
        receipt = self.prepared(); self.publish(receipt)
        self.api.pulls[0]["base"]["repo"]["full_name"] = "elsewhere/other"
        with self.assertRaisesRegex(b.BridgeError, "EXISTING_PR_NOT_OWNED"):
            self.publish(receipt)

    def test_size_limit_can_fail(self):
        with mock.patch.object(b, "MAX_TOTAL", len(self.body) - 1):
            with self.assertRaisesRegex(b.BridgeError, "DELIVERY_TOO_LARGE"):
                self.prepared()

    def test_wrong_remote_commit_content_prevents_branch_and_pr(self):
        receipt = self.prepared(); self.api.bad_commit = True
        with self.assertRaisesRegex(b.BridgeError, "REMOTE_COMMIT_FILE_BINDING_MISMATCH"):
            self.publish(receipt)
        self.assertFalse(self.api.branches)
        self.assertFalse(self.api.pulls)

    def test_large_text_report_is_not_accepted_as_raw_output(self):
        with self.assertRaisesRegex(b.BridgeError, "REPORT_TEXT_TOO_LARGE"):
            b.inspect_file("REPORT.md", b"A" * (128 * 1024 + 1))

    def test_duplicate_json_keys_and_boolean_schema_rejected(self):
        with self.assertRaisesRegex(b.BridgeError, "DUPLICATE_JSON_KEY"):
            b.object_json(b'{"id":1,"id":2}')
        self.request["schema"] = True; self.write_request()
        with self.assertRaisesRegex(b.BridgeError, "INVALID_DELIVERY_REQUEST"):
            self.prepared()

    def test_image_extension_cannot_disguise_other_bytes(self):
        with self.assertRaisesRegex(b.BridgeError, "INVALID_IMAGE_SIGNATURE"):
            b.inspect_file("overview.png", b"not an image")

    def test_os_lock_prevents_concurrent_publication_and_recovers_on_close(self):
        with b.lock(self.runtime):
            with self.assertRaisesRegex(b.BridgeError, "BRIDGE_ALREADY_RUNNING"):
                with b.lock(self.runtime):
                    self.fail("duplicate lock")
        with b.lock(self.runtime):
            pass

    def test_api_cannot_target_other_repository(self):
        api = b.Api(gh=__import__("sys").executable)
        with self.assertRaisesRegex(b.BridgeError, "ENDPOINT_NOT_ALLOWED"):
            api.request("POST", "repos/" + b.REPOSITORY + "-other/git/refs", {})

    def test_publication_release_gate_requires_review(self):
        self.release.stop()
        receipt = self.prepared()
        with self.assertRaises(FileNotFoundError):
            self.publish(receipt)
        self.assertFalse(self.posts())
        self.release.start()

    def test_freeze_rejects_unreviewed_source_and_copies_only_manifest(self):
        review_id = str(uuid.uuid4())
        tests = {"success": True, "source_sha256": b.manifest(ROOT)["sha256"], "source_unchanged": True,
                 "tests_run": 35, "discovered": 35, "failures": [], "errors": [], "skipped": []}
        b.save(self.runtime / "verification/tests.json", tests)
        review = {"status": "REWORK", "source_sha256": b.manifest(ROOT)["sha256"],
                  "tools_disabled": True, "tests_sha256": b.digest(b.read(self.runtime / "verification/tests.json"))}
        b.save(self.runtime / "reviews" / review_id / "result.json", review)
        with self.assertRaisesRegex(b.BridgeError, "CURRENT_INDEPENDENT_REVIEW_REQUIRED"):
            b.freeze(ROOT, self.runtime, review_id)
        review["status"] = "PASS"; b.save(self.runtime / "reviews" / review_id / "result.json", review)
        activation = b.freeze(ROOT, self.runtime, review_id)
        self.assertEqual(b.manifest(Path(activation["source"])), b.manifest(ROOT))
        self.assertEqual(set(p.relative_to(activation["source"]).as_posix() for p in Path(activation["source"]).rglob("*") if p.is_file()), set(b.SOURCE_FILES))
        self.release.stop(); self.app.verify_release(); self.release.start()

    def test_freeze_refuses_incomplete_test_results(self):
        b.save(self.runtime / "verification/tests.json", {"success": True})
        with self.assertRaisesRegex(b.BridgeError, "COMPLETE_CURRENT_TESTS_REQUIRED"):
            b.freeze(ROOT, self.runtime, str(uuid.uuid4()))


if __name__ == "__main__":
    unittest.main()

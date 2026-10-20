"""Run the real shared C# verifier/launcher against isolated, explicitly fake snapshots."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMPILER = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
OWNER = "BGV.Windows.SceneControl.Desktop.v1"

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")

@unittest.skipUnless(os.name == "nt", "Windows native launcher")
class NativeLauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.temp.name)
        cls.runtime = cls.base / "runtime"
        cls.desktop = cls.runtime / "desktop"
        cls.desktop.mkdir(parents=True)
        shared = (ROOT / "native/DesktopFiles.cs").read_text(encoding="utf-8").replace(
            r'E:\Github\Building-Generation-Validation\.runtime', str(cls.runtime))
        (cls.base / "Files.cs").write_text(shared, encoding="utf-8")
        (cls.base / "Harness.cs").write_text(r"""
using System;
namespace BgvSceneControl {
 internal static class LauncherHarness {
  static int Main(string[] args) {
   try {
    if(args.Length==1 && args[0]=="launch") return Launcher.Launch();
    string hash, source; Console.WriteLine(Launcher.Resolve(out hash,out source)); return 0;
   } catch(Exception e) { Console.WriteLine(e.Message); return 2; }
  }
 }
}
""", encoding="utf-8")
        cls.launcher = cls.desktop / "SceneControlLauncher.exe"
        refs = ["System", "System.Core", "System.Windows.Forms", "System.Drawing", "System.Web.Extensions"]
        common = [str(COMPILER), "/nologo", "/langversion:5", "/platform:x64"]
        subprocess.run(common + ["/out:" + str(cls.launcher), "/main:BgvSceneControl.LauncherHarness"] +
            ["/reference:" + str(COMPILER.parent / (r + ".dll")) for r in refs] +
            [str(cls.base / "Files.cs"), str(ROOT / "native/SceneControlLauncher.cs"), str(cls.base / "Harness.cs")],
            check=True, capture_output=True, timeout=60)
        fake_code = ('using System.IO;using System.Threading;class FakeApp { static void Main() { File.WriteAllText('
                     + json.dumps(str(cls.base / "FAKE-APP-LAUNCHED.txt"))
                     + ',"FIXTURE_ONLY");Thread.Sleep(1500); } }')
        (cls.base / "FakeApp.cs").write_text(fake_code, encoding="utf-8")
        cls.fake = cls.base / "FakeApp.exe"
        subprocess.run(common + ["/out:" + str(cls.fake), str(cls.base / "FakeApp.cs")], check=True, capture_output=True, timeout=60)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        snapshots = self.desktop / "snapshots"
        if snapshots.exists():
            self.assertTrue(snapshots.resolve().is_relative_to(self.base.resolve()))
            shutil.rmtree(snapshots)  # TemporaryDirectory only; never the installed runtime.
        self.marker = self.base / "FAKE-APP-LAUNCHED.txt"
        self.marker.unlink(missing_ok=True)
        write_json(self.desktop / "launcher.json", dict(owner=OWNER, sha256=digest(self.launcher)))
        self.target = self.snapshot("first")
        self.activate(self.target)

    def snapshot(self, content):
        staging = self.desktop / "snapshots/staging"
        (staging / "app").mkdir(parents=True)
        (staging / "source").mkdir()
        shutil.copyfile(self.fake, staging / "app/SceneControl.exe")
        shutil.copyfile(self.launcher, staging / "app/SceneControlLauncher.exe")
        (staging / "source/desktop.py").write_text("FIXTURE_ONLY_" + content, encoding="utf-8")
        files = {p.relative_to(staging).as_posix(): digest(p) for p in staging.rglob("*") if p.is_file()}
        sha = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        write_json(staging / "manifest.json", dict(owner=OWNER, sha256=sha, source_sha256="a" * 64, files=files))
        target = staging.parent / sha
        staging.rename(target)
        return target

    def activate(self, target, **changes):
        data = dict(owner=OWNER, sha256=target.name, source=str(target / "source"), source_sha256="a" * 64)
        data.update(changes)
        write_json(self.desktop / "activation.json", data)

    def run_launcher(self, *args, expected=0):
        run = subprocess.run([str(self.launcher), *args], capture_output=True, text=True, timeout=15)
        self.assertEqual(expected, run.returncode, run.stdout + run.stderr)
        return run.stdout.strip()

    def test_current_activation_changes_target_without_changing_launcher(self):
        self.assertEqual(str(self.target / "app/SceneControl.exe"), self.run_launcher())
        second = self.snapshot("second")
        self.activate(second)
        self.assertEqual(str(second / "app/SceneControl.exe"), self.run_launcher())

    def test_actual_launcher_starts_only_resolved_fake_child_and_records_identity(self):
        self.run_launcher("launch")
        self.assertEqual("FIXTURE_ONLY", self.marker.read_text())
        record = json.loads((self.desktop / "launch.json").read_text())
        self.assertEqual("STARTED", record["state"])
        self.assertEqual(str(self.target / "app/SceneControl.exe"), record["app"])
        self.assertGreater(record["pid"], 0)
        self.assertRegex(record["birth"], r"^[0-9]+$")
        self.assertEqual(0, record["model_calls"])

    def test_modified_source_is_rejected_before_launch(self):
        (self.target / "source/desktop.py").write_text("corrupted")
        self.assertIn("PACKAGE_CONTENT_CHANGED", self.run_launcher("launch", expected=2))
        self.assertFalse(self.marker.exists())

    def test_unlisted_file_is_rejected_before_launch(self):
        (self.target / "unlisted.txt").write_text("unknown")
        self.assertIn("PACKAGE_EXTRA_OR_MISSING_FILE", self.run_launcher("launch", expected=2))
        self.assertFalse(self.marker.exists())

    def test_wrong_activation_owner_and_path_and_hash_rejected(self):
        for changes, reason in ((dict(owner="another-system"), "ACTIVATION_IDENTITY_INVALID"),
                                (dict(source=str(self.base)), "ACTIVATION_SOURCE_INVALID"),
                                (dict(source_sha256="b"*64), "ACTIVATION_SOURCE_HASH_INVALID")):
            self.activate(self.target, **changes)
            self.assertIn(reason, self.run_launcher("launch", expected=2))
            self.assertFalse(self.marker.exists())

    def test_unowned_stable_entry_rejected(self):
        write_json(self.desktop / "launcher.json", dict(owner="unknown", sha256=digest(self.launcher)))
        self.assertIn("LAUNCHER_IDENTITY_INVALID", self.run_launcher("launch", expected=2))
        self.assertFalse(self.marker.exists())

    def test_launcher_hash_mismatch_rejected(self):
        write_json(self.desktop / "launcher.json", dict(owner=OWNER, sha256="0"*64))
        self.assertIn("LAUNCHER_IDENTITY_INVALID", self.run_launcher("launch", expected=2))

    def test_manifest_changed_without_matching_content_address_rejected(self):
        p = self.target / "manifest.json"
        record = json.loads(p.read_text()); record["files"]["source/desktop.py"] = "0"*64
        write_json(p, record)
        self.assertIn("PACKAGE_MANIFEST_CHANGED", self.run_launcher("launch", expected=2))

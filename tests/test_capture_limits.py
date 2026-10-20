"""Real owned-process capture tests. Only short newly created children are used.
Copy this file to tests/test_capture_limits.py; it imports production winproc directly.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent/"researchops/winproc.py").exists())
sys.path.insert(0, str(ROOT))
from researchops import winproc


@unittest.skipUnless(os.name == "nt", "Windows only")
class CaptureLimits(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bgv-capture-test-")
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.seen = []

    def run_child(self, script, timeout=5, prompt=""):
        return winproc.run_owned([sys.executable, "-I", "-B", "-c", script], prompt,
                                 self.root, dict(os.environ), timeout,
                                 lambda pid, birth: self.seen.append((pid, birth)), 256)

    def assert_own_children_dead(self):
        for pid, _ in self.seen:
            self.assertIsNone(winproc.identity(pid))
        self.assertIsNotNone(winproc.identity(os.getpid()))

    def test_prompt_stdout_stderr_positive(self):
        rc, out, err, _ = self.run_child("import sys; print(sys.stdin.read()); print('E',file=sys.stderr)", prompt="safe-input")
        self.assertEqual((rc, out, err), (0, "safe-input" + os.linesep, "E" + os.linesep))
        self.assert_own_children_dead()

    def test_exact_combined_byte_limit_is_accepted(self):
        with patch.object(winproc, "OWNED_OUTPUT_LIMIT_BYTES", 65536):
            rc, out, err, _ = self.run_child("import os; os.write(1,b'a'*32768); os.write(2,b'b'*32768)")
        self.assertEqual((rc, len(out), len(err)), (0, 32768, 32768))

    def test_multichunk_input_and_output_are_not_truncated(self):
        prompt = "safe-data-" * 20000
        rc, out, err, _ = self.run_child("import sys; sys.stdout.write(sys.stdin.read())", prompt=prompt)
        self.assertEqual((rc, out, err), (0, prompt, ""))

    def test_last_chunk_overflow_after_fast_parent_exit_is_rejected(self):
        with patch.object(winproc, "OWNED_OUTPUT_LIMIT_BYTES", 65536):
            for _ in range(8):
                rc, out, err, _ = self.run_child("import os; os.write(1,b'x'*65537)")
                self.assertEqual((rc, out, err), (111, "", "OWNED_PROCESS_OUTPUT_LIMIT"))

    def test_stdout_overflow_discards_everything(self):
        with patch.object(winproc, "OWNED_OUTPUT_LIMIT_BYTES", 65536):
            rc, out, err, seconds = self.run_child("import os,time; os.write(1,b'x'*2097152); time.sleep(30)")
        self.assertEqual((rc, out, err), (111, "", "OWNED_PROCESS_OUTPUT_LIMIT"))
        self.assertLess(seconds, 3)
        self.assert_own_children_dead()

    def test_combined_stdout_stderr_overflow(self):
        with patch.object(winproc, "OWNED_OUTPUT_LIMIT_BYTES", 65536):
            rc, out, err, _ = self.run_child("import os,time; os.write(1,b'a'*40000); os.write(2,b'b'*40000); time.sleep(30)")
        self.assertEqual((rc, out, err), (111, "", "OWNED_PROCESS_OUTPUT_LIMIT"))
        self.assert_own_children_dead()

    def test_infinite_stderr_is_bounded(self):
        with patch.object(winproc, "OWNED_OUTPUT_LIMIT_BYTES", 65536):
            rc, out, err, seconds = self.run_child("import os\nwhile True: os.write(2,b'x'*8192)")
        self.assertEqual((rc, out, err), (111, "", "OWNED_PROCESS_OUTPUT_LIMIT"))
        self.assertLess(seconds, 3)
        self.assert_own_children_dead()

    def test_timeout_discards_partial_raw_output(self):
        rc, out, err, seconds = self.run_child("import os,time; os.write(1,b'unfinished'); time.sleep(30)", timeout=0.2)
        self.assertEqual((rc, out, err), (1460, "", "OWNED_PROCESS_TIMEOUT"))
        self.assertLess(seconds, 3)
        self.assert_own_children_dead()

    def test_crashed_root_exit_code_is_preserved(self):
        rc, out, err, _ = self.run_child("import os; os.write(1,b'safe'); os._exit(7)")
        self.assertEqual((rc, out, err), (7, "safe", ""))
        self.assert_own_children_dead()

    def test_grandchild_holding_pipes_is_terminated_with_private_job(self):
        code = "import subprocess,sys; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']); print(p.pid,flush=True)"
        rc, out, err, seconds = self.run_child(code)
        self.assertEqual(rc, 0)
        self.assertIsNone(winproc.identity(int(out.strip())))
        self.assertLess(seconds, 3)
        self.assert_own_children_dead()

    def test_registration_callback_failure_kills_only_its_child(self):
        def stop(pid, birth):
            self.seen.append((pid, birth))
            raise RuntimeError("injected registration failure")
        with self.assertRaisesRegex(RuntimeError, "injected"):
            winproc.run_owned([sys.executable, "-c", "import time;time.sleep(30)"], "", self.root,
                              dict(os.environ), 3, stop, 256)
        self.assert_own_children_dead()

    def test_controller_crash_at_creation_and_registration_does_not_orphan(self):
        source = Path(winproc.__file__).resolve()
        for stage in ("created", "registered"):
            target = self.root/(stage + ".json")
            body = ("import importlib.util,json,os,sys\n"
                    f"s=importlib.util.spec_from_file_location('p',{str(source)!r}); p=importlib.util.module_from_spec(s); s.loader.exec_module(p)\n"
                    "def fault(stage,pid):\n"
                    f" if stage=={stage!r}:\n"
                    f"  open({str(target)!r},'w').write(json.dumps([pid,p.identity(pid)])); os._exit(73)\n"
                    "p.checkpoint=fault\n"
                    "p.run_owned([sys.executable,'-c','import time;time.sleep(30)'],'',os.getcwd(),dict(os.environ),5,lambda *a:None,256)\n")
            process = subprocess.run([sys.executable, "-I", "-B", "-c", body], cwd=self.root,
                                     capture_output=True, timeout=8, creationflags=0x08000000)
            self.assertEqual(process.returncode, 73)
            pid, birth = json.loads(target.read_text())
            for _ in range(100):
                if winproc.identity(pid) is None:
                    break
                time.sleep(0.02)
            self.assertIsNone(winproc.identity(pid))
        self.assertIsNotNone(winproc.identity(os.getpid()))


if __name__ == "__main__":
    unittest.main(verbosity=2)

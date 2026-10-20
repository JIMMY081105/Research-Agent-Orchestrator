"""Real Windows owned Job/process tests, plus bounded private-protocol behavior."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock
from researchops.worker_rpc import NativeProcess, Rpc
from researchops.worker_store import WorkerError
from researchops import winproc


class WorkerRpcTests(unittest.TestCase):
    def test_identity_persisted_before_child_executes_and_private_stdio_works(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'started.txt'
            def before(pid, birth):
                self.assertFalse(marker.exists())
                self.assertEqual(winproc.identity(pid), birth)
            script = "from pathlib import Path;import sys;Path('started.txt').write_text('yes');print(sys.stdin.readline().strip(),flush=True)"
            child = NativeProcess([sys.executable, '-c', script], directory, dict(os.environ), before)
            try:
                child.stdin.write(b'owned\n'); child.stdin.flush()
                self.assertEqual(child.stdout.readline().strip(), b'owned')
                self.assertEqual(marker.read_text(), 'yes')
            finally: child.close()

    def test_failed_durable_callback_never_runs_child(self):
        with tempfile.TemporaryDirectory() as directory:
            def fail(pid, birth): raise RuntimeError('simulated journal failure')
            with self.assertRaises(RuntimeError):
                NativeProcess([sys.executable, '-c', "from pathlib import Path;Path('must-not-exist').touch()"], directory, dict(os.environ), fail)
            self.assertFalse((Path(directory) / 'must-not-exist').exists())

    def test_close_kills_only_retained_owned_job(self):
        with tempfile.TemporaryDirectory() as directory:
            old = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(30)'], creationflags=0x08000000)
            child = NativeProcess([sys.executable, '-c', 'import time;time.sleep(30)'], directory, dict(os.environ), lambda *a: None)
            try:
                self.assertTrue(child.alive()); child.close()
                self.assertFalse(child.alive()); self.assertIsNone(old.poll())
            finally:
                child.close(); old.terminate(); old.wait(5)

    def rpc(self, incoming):
        rpc = Rpc.__new__(Rpc); rpc.serial = 0; rpc.error = None; rpc.backlog = []
        rpc.messages = queue.Queue(); rpc.send = Mock(); rpc.process = Mock()
        for message in incoming: rpc.messages.put_nowait(message)
        return rpc

    def test_native_response_id_matched_and_other_events_are_not_lost(self):
        rpc = self.rpc([{'method': 'event', 'params': {}}, {'id': 1, 'result': {'ok': True}}])
        self.assertEqual(rpc.call('test', {}), {'ok': True})
        self.assertEqual(rpc.drain(), [{'method': 'event', 'params': {}}])

    def test_provider_error_is_categorized_without_sensitive_raw_diagnostics(self):
        rpc = self.rpc([{'id': 1, 'error': {'code': -1, 'message': 'secret must not be printed'}}])
        with self.assertRaisesRegex(WorkerError, '^WORKER_RPC_REJECTED_N1$'): rpc.call('test', {})

    def test_reasoning_and_oversized_lines_do_not_enter_visible_queue(self):
        import io
        rpc = self.rpc([])
        rpc.process.stdout = io.BytesIO(b'{"method":"item/reasoning/textDelta","params":{"delta":"hidden"}}\n'
            b'{"method":"item/completed","params":{"item":{"type":"reasoning","text":"hidden"}}}\n'
            b'{"method":"item/agentMessage/delta","params":{"delta":"visible"}}\n')
        rpc._read(); self.assertEqual(rpc.messages.qsize(), 1)
        self.assertEqual(rpc.messages.get()['params']['delta'], 'visible')
        rpc.process.stdout = io.BytesIO(b'x' * (1024 * 1024 + 1)); rpc._read()
        self.assertEqual(rpc.error, 'WORKER_EVENT_TOO_LARGE')


if __name__ == '__main__': unittest.main()

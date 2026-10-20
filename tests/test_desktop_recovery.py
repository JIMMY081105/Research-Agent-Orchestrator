"""Failures must never create duplicates or adopt an old PID."""
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch
from researchops.desktop_recovery import UI_OWNER, decide

SHA = 'a' * 64

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.receipt = dict(owner=UI_OWNER, read_only=True, pid=123, birth='456', source_sha256=SHA)
        self.response = dict(read_only=True, service=dict(owner=UI_OWNER, read_only=True, pid=123, bundle_sha256=SHA))
    def test_matching_native_identity_and_api_is_ready(self):
        self.assertEqual(decide(self.receipt, self.response, SHA, lambda _: '456', True), 'READY')
    def test_first_install_is_startable(self):
        self.assertEqual(decide(None, None, SHA, lambda _: None), 'STARTABLE')
    def test_dead_owned_process_is_startable(self):
        self.assertEqual(decide(self.receipt, None, SHA, lambda _: None), 'STARTABLE')
    def test_pid_reuse_is_not_original_alive(self):
        self.assertEqual(decide(self.receipt, None, SHA, lambda _: '999'), 'STARTABLE')
    def test_alive_unresponsive_is_never_restarted(self):
        self.assertEqual(decide(self.receipt, None, SHA, lambda _: '456'), 'OWNED_PROCESS_UNRESPONSIVE')
    def test_unknown_birth_is_blocked(self):
        self.assertEqual(decide(self.receipt, None, SHA, lambda _: 'UNKNOWN'), 'PROCESS_IDENTITY_UNKNOWN')
    def test_foreign_port_is_never_taken_over(self):
        self.assertEqual(decide(None, None, SHA, lambda _: None, True), 'PORT_IDENTITY_UNVERIFIED')
    def test_wrong_api_pid_is_not_ready(self):
        self.response['service']['pid'] = 999
        self.assertEqual(decide(self.receipt, self.response, SHA, lambda _: '456'), 'OWNED_PROCESS_UNRESPONSIVE')
    def test_wrong_api_version_is_not_ready(self):
        self.response['service']['bundle_sha256'] = 'b' * 64
        self.assertEqual(decide(self.receipt, self.response, SHA, lambda _: '456'), 'OWNED_PROCESS_UNRESPONSIVE')
    def test_wrong_api_owner_or_permissions_is_not_ready(self):
        for key, value in (('owner', 'foreign'), ('read_only', False)):
            response = dict(read_only=True, service={**self.response['service'], key: value})
            self.assertEqual(decide(self.receipt, response, SHA, lambda _: '456'), 'OWNED_PROCESS_UNRESPONSIVE')
    def test_other_live_bundle_is_not_adopted(self):
        self.receipt['source_sha256'] = 'b' * 64
        self.assertEqual(decide(self.receipt, None, SHA, lambda _: '456'), 'OTHER_VERSION_RUNNING')
    def test_malformed_receipt_is_blocked(self):
        for value in ({}, {**self.receipt, 'pid': '123'}, {**self.receipt, 'birth': 'bad'}):
            self.assertEqual(decide(value, None, SHA, lambda _: None), 'RECEIPT_UNVERIFIED')
    def test_stale_api_without_living_process_is_not_ready(self):
        self.assertEqual(decide(self.receipt, self.response, SHA, lambda _: None), 'PORT_IDENTITY_UNVERIFIED')

    def test_bootstrap_will_not_follow_local_service_redirect(self):
        import desktop
        hits = []
        class Trap(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                hits.append(self.path)
                self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
        trap = ThreadingHTTPServer(('127.0.0.1', 0), Trap)
        class Redirect(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                self.send_response(302)
                self.send_header('Location', 'http://127.0.0.1:' + str(trap.server_port) + '/must-not-read')
                self.end_headers()
        redirect = ThreadingHTTPServer(('127.0.0.1', 0), Redirect)
        threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (trap, redirect)]
        for thread in threads: thread.start()
        try:
            with tempfile.TemporaryDirectory() as folder, patch.object(desktop, 'URL', 'http://127.0.0.1:' + str(redirect.server_port)):
                result = desktop.probe(Path(folder), SHA)
                self.assertNotEqual(result['state'], 'READY')
                self.assertEqual(hits, [], 'bootstrap followed an unverified HTTP redirect')
        finally:
            for server in (redirect, trap): server.shutdown(); server.server_close()
            for thread in threads: thread.join(2)

if __name__ == '__main__':
    unittest.main()

"""Real loopback HTTP negatives: GET cannot execute and POST requires exact origin/token."""
import http.client
import json
import threading
import unittest
from unittest.mock import Mock
from researchops.dashboard_server import LocalServer


class WorkerHttpTests(unittest.TestCase):
    def setUp(self):
        self.worker = Mock()
        self.worker.capability.return_value = {'enabled': True}
        self.worker.status.return_value = {'turns': []}
        self.worker.submit.return_value = {'state': 'QUEUED'}
        cache = Mock(); cache.snapshot.return_value = {}
        self.server = LocalServer(('127.0.0.1', 0), cache, {}, worker=self.worker)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.addCleanup(self.close)
        self.origin = 'http://127.0.0.1:' + str(self.server.server_port)

    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)

    def request(self, method, path, body=None, **headers):
        client = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        try:
            client.request(method, path, body=body, headers=headers)
            result = client.getresponse(); data = result.read()
            return result.status, json.loads(data) if data and data[:1] == b'{' else data
        finally: client.close()

    def headers(self):
        return {'Origin': self.origin, 'Content-Type': 'application/json', 'X-BGV-CSRF': self.server.csrf_token}

    def test_get_status_cannot_submit_or_start_model(self):
        self.assertEqual(self.request('GET', '/api/worker/status')[0], 200)
        self.assertEqual(self.request('GET', '/api/worker/capabilities')[0], 200)
        self.worker.submit.assert_not_called(); self.worker.decide.assert_not_called()

    def test_cross_origin_missing_token_or_wrong_token_rejected(self):
        for headers in ({}, {**self.headers(), 'Origin': 'https://example.org'},
                        {**self.headers(), 'X-BGV-CSRF': 'bad'}):
            with self.subTest(headers=list(headers)):
                self.assertEqual(self.request('POST', '/api/worker/turns', '{}', **headers)[0], 403)
        self.worker.submit.assert_not_called()

    def test_exact_post_routes_only_and_duplicate_json_rejected(self):
        headers = self.headers()
        for path in ('/api/worker/shell', '/api/worker/turns?mode=full', '/api/worker/turns/'):
            self.assertEqual(self.request('POST', path, '{}', **headers)[0], 405)
        self.assertEqual(self.request('POST', '/api/worker/turns', '{"id":1,"id":2}', **headers)[0], 400)
        self.worker.submit.assert_not_called()

    def test_native_actions_route_only_to_owned_worker_store(self):
        for path, name in (('turns', 'submit'), ('approval', 'decide'), ('cancel', 'cancel')):
            getattr(self.worker, name).return_value = {'ok': True}
            code, _ = self.request('POST', '/api/worker/' + path, '{"test":"value"}', **self.headers())
            self.assertEqual(code, 202)
            getattr(self.worker, name).assert_called_once_with({'test': 'value'})

    def test_unicode_worker_payload_is_not_limited_by_old_text_analysis_bytes(self):
        body = json.dumps({'prompt': '\u4e2d' * 15000}, ensure_ascii=False).encode('utf-8')
        self.assertGreater(len(body), 32768)
        self.assertEqual(self.request('POST', '/api/worker/turns', body, **self.headers())[0], 202)
        self.worker.submit.assert_called_once_with({'prompt': '\u4e2d' * 15000})


if __name__ == '__main__': unittest.main()

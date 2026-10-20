"""Fail-capable local HTTP tests; no models, real database or remote SSH."""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from researchops.dashboard_server import LocalServer, StatusCache, write_record
from researchops.dashboard_tasks import TaskError, LIMITS


class FakeCache:
    def __init__(self):
        self.value = {"read_only": True, "engines": {"codex": {"state": "IDLE"}}}
        self.reads = 0
    def snapshot(self):
        self.reads += 1
        return self.value


class DashboardHTTPTests(unittest.TestCase):
    def setUp(self):
        self.cache = FakeCache()
        self.server = LocalServer(("127.0.0.1", 0), self.cache,
                                  {"/": ("text/html", b"local page"), "/assets/david.jpg": ("image/jpeg", b"image")})
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)
    def request(self, path="/api/status", method="GET", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result
    def test_real_get_reads_only_the_cache(self):
        for _ in range(3):
            code, headers, body = self.request()
            self.assertEqual(code, 200)
            self.assertTrue(json.loads(body)["read_only"])
            self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(self.cache.reads, 3)
    def test_foreign_host_rejected_before_cache(self):
        self.assertEqual(self.request(headers={"Host": "attacker.example"})[0], 403)
        self.assertEqual(self.cache.reads, 0)
    def test_foreign_origin_rejected_before_cache(self):
        self.assertEqual(self.request(headers={"Origin": "https://attacker.example"})[0], 403)
        self.assertEqual(self.cache.reads, 0)
    def test_cross_site_requests_rejected(self):
        self.assertEqual(self.request(headers={"Sec-Fetch-Site": "cross-site"})[0], 403)
    def test_same_origin_allowed(self):
        origin = "http://127.0.0.1:" + str(self.server.server_port)
        self.assertEqual(self.request(headers={"Origin": origin, "Sec-Fetch-Site": "same-origin"})[0], 200)
    def test_mutation_methods_cannot_dispatch(self):
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            self.assertEqual(self.request(method=method)[0], 405)
        self.assertEqual(self.cache.reads, 0)
    def test_no_arbitrary_paths_or_query_commands(self):
        for path in ("/.runtime/machine.json", "/../../.ssh/config", "/api/status?command=run", "/api/submit", "/assets/"):
            self.assertEqual(self.request(path)[0], 404)
        self.assertEqual(self.cache.reads, 0)
    def test_health_discloses_only_service_identity(self):
        code, headers, body = self.request("/api/health")
        self.assertEqual(code, 200)
        self.assertEqual(set(json.loads(body)), {"owner", "read_only"})
    def test_security_headers_and_static_allowlist(self):
        code, headers, body = self.request("/")
        self.assertEqual((code, body), (200, b"local page"))
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Cross-Origin-Resource-Policy"], "same-origin")
    def test_head_has_no_body(self):
        self.assertEqual(self.request("/", "HEAD")[2], b"")
    def test_composer_default_is_disabled_even_for_task_endpoint(self):
        code, _, body = self.request("/api/composer")
        self.assertEqual(code, 200)
        self.assertFalse(json.loads(body)["enabled"])
        self.assertIsNone(json.loads(body)["csrf_token"])
        self.assertEqual(self.request("/api/tasks", "POST")[0], 405)
    def test_large_status_refused(self):
        self.cache.value = {"large": "x" * (1024 * 1024)}
        self.assertEqual(self.request()[0], 503)
    def test_nonloopback_bind_refused(self):
        with self.assertRaises(ValueError):
            LocalServer(("0.0.0.0", 0), self.cache, {})


class DashboardCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = Path(self.temp.name)
        self.config = {"ssh": "fixed-ssh", "ssh_alias": "fixed-alias"}
    def tearDown(self):
        self.temp.cleanup()
    def test_http_snapshot_does_not_start_ssh_or_sqlite(self):
        def forbidden(*args, **kwargs):
            self.fail("a cache read performed an observation")
        cache = StatusCache(self.runtime, self.config, forbidden, forbidden)
        for _ in range(100):
            self.assertTrue(cache.snapshot()["service"]["read_only"])
        self.assertEqual(cache.gpu_checks, 0)
    def test_read_failure_is_unknown_not_old_running(self):
        def failing(_):
            raise OSError("private-path-and-secret")
        cache = StatusCache(self.runtime, self.config, failing)
        cache.state = {"engines": {"codex": {"state": "RUNNING"}}}
        cache.sample_state()
        value = cache.snapshot()
        self.assertEqual(value["reason"], "STATE_UNAVAILABLE")
        self.assertNotIn("private-path", json.dumps(value))
        self.assertNotIn("RUNNING", json.dumps(value))
    def test_gpu_failure_does_not_erase_success(self):
        import datetime as dt
        stamp = dt.datetime.now(dt.timezone.utc).isoformat()
        good = {"status": "OK", "observed_at": stamp, "gpus": [], "processes": []}
        cache = StatusCache(self.runtime, self.config, gpu_reader=lambda *a, **k: good)
        cache.sample_gpu()
        cache.gpu_reader = lambda *a, **k: {"status": "ERROR", "failure": "NETWORK", "observed_at": stamp}
        cache.sample_gpu()
        self.assertIs(cache.last_gpu, good)
        self.assertEqual(cache.gpu_checks, 2)
    def test_owned_record_is_written_only_at_given_path(self):
        directory = self.runtime / "dashboard"; directory.mkdir()
        outside = self.runtime / "untouched.txt"; outside.write_text("original")
        write_record(directory / "service.json", {"owner": "UI"})
        self.assertEqual(outside.read_text(), "original")
        self.assertEqual(json.loads((directory / "service.json").read_text())["owner"], "UI")


class ComposerHTTPTests(unittest.TestCase):
    def setUp(self):
        self.submissions = []
        owner = self
        class Composer:
            def capability(self):
                return {"enabled": True, "limits": dict(LIMITS), "action": "analyze_text", "writers": ["codex", "claude"]}
            def submit(self, value):
                owner.submissions.append(value)
                return {"id": value["id"], "state": "QUEUED", "writer": value["writer"], "reviewer": "claude", "result": None}
            def get(self, identifier):
                raise TaskError("TASK_NOT_FOUND", 404)
        self.server = LocalServer(("127.0.0.1", 0), FakeCache(), {}, composer=Composer())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.origin = "http://127.0.0.1:" + str(self.server.server_port)
        self.request_body = {"id": "bc462f29-3ac7-4a83-ab54-3cc6a35fe918", "prompt": "分析材料", "context": "给定材料", "writer": "codex"}
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)
    def request(self, method="POST", path="/api/tasks", raw=None, headers=None, duplicate=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=4)
        body = json.dumps(self.request_body).encode() if raw is None else raw
        values = {"Host": self.origin[7:], "Origin": self.origin, "X-BGV-CSRF": self.server.csrf_token,
                  "Content-Type": "application/json", "Content-Length": str(len(body)), "Sec-Fetch-Site": "same-origin"}
        if headers:
            for key, value in headers.items():
                if value is None: values.pop(key, None)
                else: values[key] = value
        connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for key, value in values.items(): connection.putheader(key, value)
        if duplicate:
            connection.putheader(*duplicate)
        connection.endheaders(body if method in ("POST", "PUT", "PATCH") else None)
        response = connection.getresponse(); result = response.status, dict(response.getheaders()), response.read()
        connection.close(); return result
    def test_capability_token_and_explicit_post(self):
        code, headers, body = self.request("GET", "/api/composer")
        self.assertEqual(code, 200); self.assertEqual(json.loads(body)["csrf_token"], self.server.csrf_token)
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        code, _, body = self.request()
        self.assertEqual(code, 202); self.assertEqual(json.loads(body)["state"], "QUEUED")
        self.assertEqual(self.submissions, [self.request_body])
    def test_post_requires_explicit_origin_csrf_and_same_site(self):
        for headers in ({"Origin": None}, {"Origin": "https://other.invalid"}, {"Host": "other.invalid"},
                        {"X-BGV-CSRF": None}, {"X-BGV-CSRF": "bad"}, {"X-BGV-CSRF": "é"},
                        {"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "none"}):
            with self.subTest(headers=headers): self.assertEqual(self.request(headers=headers)[0], 403)
        self.assertEqual(self.submissions, [])
    def test_duplicate_security_and_framing_headers_are_rejected(self):
        for key, value, expected in (("Origin", self.origin, 403), ("Host", self.origin[7:], 403),
                                     ("X-BGV-CSRF", self.server.csrf_token, 403), ("Sec-Fetch-Site", "same-origin", 403),
                                     ("Content-Length", "2", 400), ("Content-Type", "application/json", 415)):
            with self.subTest(header=key): self.assertEqual(self.request(duplicate=(key, value))[0], expected)
        self.assertEqual(self.submissions, [])
    def test_json_mime_framing_size_and_invalid_json(self):
        for headers, expected in (({"Content-Type": "text/plain"}, 415), ({"Content-Length": "65537"}, 413),
                                  ({"Content-Length": None}, 400), ({"Content-Length": "-1"}, 400),
                                  ({"Transfer-Encoding": "chunked"}, 400), ({"Content-Encoding": "gzip"}, 400)):
            with self.subTest(headers=headers): self.assertEqual(self.request(headers=headers)[0], expected)
        for raw in (b'{"id":"first","id":"second"}', b'{"value":NaN}', b'not json', b'\xff'):
            with self.subTest(raw=raw): self.assertEqual(self.request(raw=raw)[0], 400)
        self.assertEqual(self.submissions, [])
    def test_put_aliases_other_paths_and_unregistered_get_cannot_submit(self):
        for method in ("PUT", "PATCH", "DELETE", "OPTIONS"):
            self.assertEqual(self.request(method)[0], 405)
        self.assertEqual(self.request(path="/api/tasks?run=now")[0], 405)
        self.assertEqual(self.request("GET", "/api/tasks/" + self.request_body["id"])[0], 404)
        self.assertEqual(self.request("GET", "/api/tasks/../../secret")[0], 404)
        self.assertEqual(self.submissions, [])


if __name__ == "__main__":
    unittest.main()

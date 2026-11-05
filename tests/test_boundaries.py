import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import random
import tempfile
import threading
import unittest

from ops_agent.collectors import Collector, LogTail, ServiceConfig, load_config, validate_loopback_url
from ops_agent.demo import seed
from ops_agent.engine import Engine
from ops_agent.server import ConsoleServer
from ops_agent.storage import Store


class CollectorTests(unittest.TestCase):
    def test_loopback_only(self):
        self.assertEqual(validate_loopback_url("http://127.0.0.1:9000/health"), "http://127.0.0.1:9000/health")
        for url in ("https://127.0.0.1:9000", "http://example.com:80/health", "http://localhost:80", "http://127.0.0.1/", "http://127.0.0.1:80/?token=x", "http://u:p@127.0.0.1:80", "http://169.254.169.254:80/"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_loopback_url(url)

    def test_config_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text('[agent]\ninterval_seconds=0\n[[services]]\nname="api"\nhealth_url="http://127.0.0.1:9000/health"')
            with self.assertRaises(ValueError):
                load_config(path)
            path.write_text('[[services]]\nname="api"\nhealth_url="http://127.0.0.1:9000/health"\nlog_file="a.log"')
            cfg = load_config(path)
            self.assertEqual(cfg.services[0].log_file, Path(tmp) / "a.log")

    def test_log_tail_rotation_and_redaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.log"
            path.write_text('first\n{"level":"ERROR","message":"token=secret error"}\n')
            tail = LogTail(path)
            logs = tail.read()
            self.assertEqual(len(logs), 2)
            self.assertNotIn("secret", logs[-1].as_dict()["message"])
            self.assertEqual(tail.read(), ())
            path.rename(path.with_suffix(".old"))
            path.write_text("rotated\n")
            self.assertEqual(tail.read()[0].message, "rotated")
            path.write_text("a\n")
            self.assertEqual(tail.read()[0].message, "a")

    def test_log_tail_large_files_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.log"
            path.write_text("row\n" * 100000)
            self.assertLessEqual(len(LogTail(path).read()), 12)

    def probe(self, body, status=200, location=None):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(status)
                if location:
                    self.send_header("Location", location)
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *_):
                pass
        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            collector = Collector(ServiceConfig("api", f"http://127.0.0.1:{server.server_port}/health"))
            return collector.collect()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_live_health_contract(self):
        result = self.probe(b'{"latency_ms":80,"error_rate":0.01,"memory_pct":44,"cpu_pct":30,"health_ok":true}')
        self.assertTrue(result.health_ok)
        self.assertEqual(result.latency_ms, 80)

    def test_redirect_not_followed(self):
        result = self.probe(b"", 302, "http://192.0.2.1/private")
        self.assertFalse(result.health_ok)

    def test_large_and_invalid_health_bodies(self):
        for body in (b"x" * 17000, b"[]", b'{"memory_pct":200}', b'{"health_ok":"yes"}'):
            with self.subTest(body=body[:40]), self.assertRaises(ValueError):
                self.probe(body)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.engine = Engine(self.store)
        seed(self.engine, random.Random(42))
        self.server = ConsoleServer(self.engine, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.store.close()

    def request(self, method, path, payload=None, token=True, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        request_headers = dict(headers or {})
        if token:
            request_headers["X-Ops-Token"] = self.server.csrf_token
        if payload is not None:
            request_headers["Content-Type"] = "application/json"
        try:
            conn.request(method, path, json.dumps(payload) if payload is not None else None, request_headers)
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def test_overview_and_security_headers(self):
        status, headers, body = self.request("GET", "/api/overview")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["mode"], "demo")
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_missing_token_rejected(self):
        self.assertEqual(self.request("POST", "/api/demo", {"scenario":"cascade"}, token=False)[0], 403)

    def test_cross_origin_rejected(self):
        self.assertEqual(self.request("POST", "/api/demo", {"scenario":"cascade"}, headers={"Origin":"https://evil.test"})[0], 403)

    def test_dns_rebinding_host_rejected(self):
        self.assertEqual(self.request("GET", "/api/overview", headers={"Host":"attacker.test:8765"})[0], 403)

    def test_demo_and_ack_flow(self):
        status, _, body = self.request("POST", "/api/demo", {"scenario":"latency"})
        self.assertEqual(status, 200)
        incident = json.loads(body)["incidents"][0]
        status, _, body = self.request("POST", f"/api/incidents/{incident['id']}/ack", {})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])

    def test_unknown_scenario_and_path(self):
        self.assertEqual(self.request("POST", "/api/demo", {"scenario":"execute-command"})[0], 400)
        self.assertEqual(self.request("GET", "/../../etc/passwd")[0], 404)

    def test_monitor_cannot_inject(self):
        self.engine.mode = "monitor"  # Isolate route gate with in-memory fixture.
        self.assertEqual(self.request("POST", "/api/demo", {"scenario":"latency"})[0], 409)

    def test_payload_limits(self):
        self.assertEqual(self.request("POST", "/api/demo", {"scenario":"x" * 3000})[0], 413)

    def test_health_and_prometheus(self):
        self.assertEqual(json.loads(self.request("GET", "/healthz")[2])["execution_enabled"], False)
        self.assertIn(b"ops_agent_samples_total", self.request("GET", "/metrics")[2])

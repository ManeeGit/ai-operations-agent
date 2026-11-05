"""Loopback-only read console, synthetic injection and local acknowledgement."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import random
import secrets
import threading
from urllib.parse import urlsplit

from .demo import inject, SCENARIOS
from .engine import Engine

STATIC = Path(__file__).with_name("static")


class ConsoleServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, engine: Engine, port: int = 8765):
        self.engine = engine
        self.csrf_token = secrets.token_urlsafe(32)
        self.rng = random.Random(42)
        self.demo_lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(("127.0.0.1", port), Handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    server: ConsoleServer

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, fmt, *args):
        # Explicit audit events cover state transitions without retaining request paths.
        pass

    def send_data(self, status: int, payload, content_type="application/json; charset=utf-8"):
        data = json.dumps(payload, allow_nan=False).encode() if isinstance(payload, (dict, list)) else payload
        if isinstance(data, str):
            data = data.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def allowed_request(self) -> bool:
        port = self.server.server_address[1]
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host") not in allowed:
            self.send_data(403, {"error": "Invalid Host header"})
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://{h}" for h in allowed}:
            self.send_data(403, {"error": "Cross-origin requests are disabled"})
            return False
        return True

    def overview(self):
        return {**self.server.engine.overview(), "csrf_token": self.server.csrf_token}

    def do_GET(self):
        if not self.allowed_request():
            return
        route = urlsplit(self.path).path
        if route == "/api/overview":
            return self.send_data(200, self.overview())
        if route == "/healthz":
            return self.send_data(200, {"status": "ok", "mode": self.server.engine.mode, "execution_enabled": False})
        if route == "/metrics":
            return self.send_data(200, self.server.engine.prometheus(), "text/plain; version=0.0.4; charset=utf-8")
        files = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"), "/style.css": ("style.css", "text/css; charset=utf-8")}
        if route in files:
            filename, content_type = files[route]
            try:
                return self.send_data(200, (STATIC / filename).read_bytes(), content_type)
            except FileNotFoundError:
                return self.send_data(503, {"error": "Console assets unavailable"})
        self.send_data(404, {"error": "Not found"})

    def do_POST(self):
        if not self.allowed_request():
            return
        if not secrets.compare_digest(self.headers.get("X-Ops-Token", ""), self.server.csrf_token):
            return self.send_data(403, {"error": "Missing or invalid local request token"})
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self.send_data(415, {"error": "Expected application/json"})
        if self.headers.get("Transfer-Encoding"):
            return self.send_data(400, {"error": "Transfer-Encoding is unsupported"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 1 <= size <= 2048:
                return self.send_data(413, {"error": "Body must contain 1 to 2048 bytes"})
            body = self.rfile.read(size)
            if len(body) != size:
                return self.send_data(400, {"error": "Incomplete body"})
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError("Expected JSON object")
        except (ValueError, UnicodeDecodeError, TimeoutError):
            return self.send_data(400, {"error": "Invalid JSON body"})
        route = urlsplit(self.path).path
        if route == "/api/demo":
            if self.server.engine.mode != "demo":
                return self.send_data(409, {"error": "Synthetic injection is disabled in monitor mode"})
            scenario = payload.get("scenario")
            if scenario not in SCENARIOS or set(payload) != {"scenario"}:
                return self.send_data(400, {"error": "Unknown scenario"})
            if not self.server.demo_lock.acquire(blocking=False):
                return self.send_data(409, {"error": "A synthetic scenario is already running"})
            try:
                inject(self.server.engine, scenario, self.server.rng)
                return self.send_data(200, self.overview())
            finally:
                self.server.demo_lock.release()
        prefix, suffix = "/api/incidents/", "/ack"
        if route.startswith(prefix) and route.endswith(suffix):
            incident_id = route[len(prefix):-len(suffix)]
            if len(incident_id) != 16 or any(c not in "0123456789abcdef" for c in incident_id):
                return self.send_data(400, {"error": "Invalid incident ID"})
            if payload:
                return self.send_data(400, {"error": "Acknowledgement body must be empty"})
            found = self.server.engine.acknowledge(incident_id)
            return self.send_data(200 if found else 404, {"ok": found})
        self.send_data(404, {"error": "Not found"})

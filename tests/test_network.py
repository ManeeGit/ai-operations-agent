import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import time
import unittest

from ops_agent.collectors import Collector, ServiceConfig
from ops_agent.network import request_bytes


class NetworkDeadlineTests(unittest.TestCase):
    def start_server(self, handler):
        server = HTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join()))
        return f"http://127.0.0.1:{server.server_port}/health"

    def test_truncated_chunked_health_is_failure_not_uncaught(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                self.wfile.write(b"20\r\nshort")
                self.close_connection = True
            def log_message(self, *_):
                pass
        url = self.start_server(Handler)
        result = Collector(ServiceConfig("api", url)).collect()
        self.assertFalse(result.health_ok)

    def test_body_trickle_has_total_deadline(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", "20")
                self.end_headers()
                try:
                    for _ in range(20):
                        self.wfile.write(b" ")
                        self.wfile.flush()
                        time.sleep(.05)
                except (BrokenPipeError, ConnectionResetError):
                    pass
            def log_message(self, *_):
                pass
        url = self.start_server(Handler)
        started = time.monotonic()
        with self.assertRaises((TimeoutError, OSError, http.client.HTTPException)):
            request_bytes(url, timeout=.25, limit=100)
        self.assertLess(time.monotonic() - started, .8)

    def test_header_trickle_has_total_deadline(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                try:
                    for value in b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\n{}":
                        self.wfile.write(bytes([value]))
                        self.wfile.flush()
                        time.sleep(.05)
                except (BrokenPipeError, ConnectionResetError):
                    pass
            def log_message(self, *_):
                pass
        url = self.start_server(Handler)
        started = time.monotonic()
        with self.assertRaises((TimeoutError, OSError, http.client.HTTPException)):
            request_bytes(url, timeout=.25, limit=100)
        self.assertLess(time.monotonic() - started, .8)

    def test_truncated_content_length_is_rejected(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", "100")
                self.end_headers()
                self.wfile.write(b"{}")
                self.close_connection = True
            def log_message(self, *_):
                pass
        url = self.start_server(Handler)
        with self.assertRaises(http.client.IncompleteRead):
            request_bytes(url, timeout=2, limit=1024)

    def test_fifo_log_is_rejected_without_blocking(self):
        import os
        import tempfile
        from pathlib import Path
        from ops_agent.collectors import LogTail
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pipe"
            os.mkfifo(path)
            started = time.monotonic()
            with self.assertRaises(ValueError):
                LogTail(path).read()
            self.assertLess(time.monotonic() - started, .5)

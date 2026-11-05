"""A harmless local health endpoint for testing the live collector.

Run with --scenario latency, errors, memory, or healthy. No external requests.
"""
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=("healthy", "latency", "errors", "memory"), default="healthy")
    parser.add_argument("--port", type=int, default=9000)
    args = parser.parse_args()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            payload = {"health_ok": True, "latency_ms": 2400 if args.scenario == "latency" else 80,
                "error_rate": 0.2 if args.scenario == "errors" else 0.002,
                "cpu_pct": 30, "memory_pct": 96 if args.scenario == "memory" else 42}
            body = json.dumps(payload).encode()
            self.send_response(200 if self.path == "/health" else 404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *_):
            pass
    server = HTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Synthetic example service: http://127.0.0.1:{args.port}/health", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
import http.client
from pathlib import Path
import random
import signal
import sys
import threading

from .collectors import Collector, load_config
from .demo import inject, seed, SCENARIOS
from .engine import Engine
from .server import ConsoleServer
from .storage import Store
from .triage import Triage


def poll(engine, collectors, interval, stop, cycles=0):
    count = 0
    while not stop.is_set():
        for collector in collectors:
            if stop.is_set():
                break
            try:
                engine.ingest(collector.collect())
            except (OSError, ValueError, TypeError, KeyError, http.client.HTTPException) as exc:
                engine.store.event("collector_error", f"{collector.config.name}: {type(exc).__name__}: {exc}")
        count += 1
        if cycles and count >= cycles:
            break
        stop.wait(interval)


def parser():
    root = argparse.ArgumentParser(description="Local-first operations triage. No remediation executor.")
    sub = root.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="Run a bounded synthetic replay and emit JSON")
    demo.add_argument("--scenario", choices=SCENARIOS, default="cascade")
    demo.add_argument("--output", type=Path)
    demo.add_argument("--seed", type=int, default=42)
    for name in ("serve", "monitor"):
        command = sub.add_parser(name, help="Serve a local console" if name == "serve" else "Poll configured local services without a console")
        command.add_argument("--config", type=Path, required=name == "monitor")
        command.add_argument("--db", help="SQLite path; demo and monitor use separate defaults")
        command.add_argument("--ollama-model", help="Opt in to a local Ollama model; no model is downloaded automatically")
        if name == "serve":
            command.add_argument("--port", type=int, default=8765)
        else:
            command.add_argument("--cycles", type=int, default=0, help="0 runs until interrupted; positive value runs a bounded number of cycles")
    return root


def _run(argv=None):
    args = parser().parse_args(argv)
    if args.command == "demo":
        store = Store()
        try:
            engine = Engine(store)
            rng = random.Random(args.seed)
            seed(engine, rng)
            report = inject(engine, args.scenario, rng)
            serialized = json.dumps(report, indent=2)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(serialized + "\n")
                print(f"Synthetic report saved to {args.output}")
            else:
                print(serialized)
            return 0
        finally:
            store.close()
    if args.command == "monitor" and args.cycles < 0:
        raise ValueError("cycles must not be negative")
    if args.command == "serve" and not 1 <= args.port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    config = load_config(args.config) if args.config else None
    store = Store(args.db or (".ops-agent/monitor.sqlite3" if config else ".ops-agent/demo.sqlite3"))
    stop = threading.Event()
    thread, server = None, None
    try:
        engine = Engine(store, Triage(args.ollama_model), "monitor" if config else "demo")
        collectors = [Collector(c) for c in config.services] if config else []
        if args.command == "monitor":
            signal.signal(signal.SIGTERM, lambda *_: stop.set())
            try:
                poll(engine, collectors, config.interval_seconds, stop, args.cycles)
            except KeyboardInterrupt:
                pass
            print(json.dumps(engine.overview(), indent=2))
            return 0
        if config:
            thread = threading.Thread(target=poll, args=(engine, collectors, config.interval_seconds, stop), daemon=True)
            thread.start()
        elif not store.latest_samples():
            rng = random.Random(42)
            seed(engine, rng)
            inject(engine, "latency", rng)
        server = ConsoleServer(engine, args.port)
        def shutdown(*_):
            stop.set()
            threading.Thread(target=server.shutdown, daemon=True).start()
        signal.signal(signal.SIGTERM, shutdown)
        print(f"Operations console: http://127.0.0.1:{args.port} ({engine.mode}; remediation disabled)", flush=True)
        try:
            server.serve_forever(poll_interval=0.2)
        except KeyboardInterrupt:
            pass
        return 0
    finally:
        stop.set()
        if server:
            server.server_close()
        if thread:
            # Max 8 probes x 2 s + at most one 20 s model call before cooldown.
            thread.join(timeout=45)
        store.close()


def main(argv=None):
    try:
        return _run(argv)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"ops-agent: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

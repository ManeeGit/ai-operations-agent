"""Read-only loopback health probes and explicitly configured bounded log tails."""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import http.client
import json
import os
import stat as file_stat
from pathlib import Path
import time
import tomllib
import urllib.parse

from .models import LogEntry, Sample
from .network import request_bytes


def validate_loopback_url(url: str) -> str:
    if not isinstance(url, str) or len(url) > 1024:
        raise ValueError("invalid health URL")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "http" or parsed.username or parsed.password or parsed.fragment or parsed.query:
        raise ValueError("health endpoints must be plain HTTP loopback URLs without credentials, query, or fragment")
    # Require numeric loopback: no resolution or DNS rebinding ambiguity.
    try:
        address = ipaddress.ip_address(parsed.hostname or "")
        port = parsed.port
    except ValueError as exc:
        raise ValueError("health endpoints require a numeric loopback IP, e.g. 127.0.0.1") from exc
    if not address.is_loopback or not port or not 1 <= port <= 65535:
        raise ValueError("health endpoints require a loopback IP and explicit port")
    return url


@dataclass(frozen=True)
class ServiceConfig:
    name: str
    health_url: str
    log_file: Path | None = None

    def __post_init__(self):
        Sample(self.name, 0, 0, 0, 0)  # Reuse the identifier boundary.
        validate_loopback_url(self.health_url)


@dataclass(frozen=True)
class MonitorConfig:
    services: tuple[ServiceConfig, ...]
    interval_seconds: float = 5


def load_config(path: Path) -> MonitorConfig:
    data = tomllib.loads(path.read_text())
    if set(data) - {"agent", "services"} or set(data.get("agent", {})) - {"interval_seconds"}:
        raise ValueError("unknown configuration key")
    interval = data.get("agent", {}).get("interval_seconds", 5)
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not 1 <= interval <= 3600:
        raise ValueError("interval_seconds must be between 1 and 3600")
    entries = data.get("services", [])
    if not isinstance(entries, list) or not 1 <= len(entries) <= 8:
        raise ValueError("configure 1 to 8 services")
    services = []
    for item in entries:
        if not isinstance(item, dict) or set(item) - {"name", "health_url", "log_file"}:
            raise ValueError("unknown service configuration key")
        logfile = item.get("log_file")
        if logfile is not None and (not isinstance(logfile, str) or not logfile):
            raise ValueError("log_file must be a non-empty path")
        local_path = (path.parent / logfile).resolve() if logfile else None
        services.append(ServiceConfig(item["name"], item["health_url"], local_path))
    if len({s.name for s in services}) != len(services):
        raise ValueError("service names must be unique")
    return MonitorConfig(tuple(services), interval)


class LogTail:
    def __init__(self, path: Path):
        self.path, self.offset, self.inode = path, 0, None

    def read(self) -> tuple[LogEntry, ...]:
        # Start near EOF, handle rotation/truncation, never scan unbounded files.
        try:
            descriptor = os.open(self.path, os.O_RDONLY | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as stream:
                stat = os.fstat(stream.fileno())
                if not file_stat.S_ISREG(stat.st_mode):
                    raise ValueError("log path must be a regular file")
                reset = self.inode != stat.st_ino or stat.st_size < self.offset
                previous = 0 if reset else self.offset
                self.inode = stat.st_ino
                start = max(previous, stat.st_size - 32768)
                stream.seek(start)
                chunk = stream.read(32768)
                self.offset = stream.tell()
            lines = chunk.splitlines()
            if start > previous:
                # The read jumped into a line after rotation or a large append.
                lines = lines[1:]
            logs = []
            for raw in lines[-12:]:
                text = raw.decode("utf-8", errors="replace")
                try:
                    parsed = json.loads(text)
                except (ValueError, TypeError):
                    parsed = None
                if isinstance(parsed, dict):
                    logs.append(LogEntry(str(parsed.get("message", text)), str(parsed.get("level", "INFO"))))
                else:
                    logs.append(LogEntry(text, "ERROR" if "error" in text.lower() else "INFO"))
            return tuple(logs)
        except FileNotFoundError:
            return (LogEntry("Configured log file does not exist", "WARN"),)


class Collector:
    def __init__(self, config: ServiceConfig):
        self.config = config
        self.tail = LogTail(config.log_file) if config.log_file else None

    def collect(self) -> Sample:
        started = time.monotonic()
        logs = list(self.tail.read() if self.tail else ())
        health = True
        metrics = {}
        try:
            status, body = request_bytes(self.config.health_url, timeout=2, limit=16384,
                headers={"Accept": "application/json", "User-Agent": "ai-operations-agent/0.1"})
            if not 200 <= status < 300:
                raise OSError("health endpoint returned a non-success status")
            if body.strip():
                metrics = json.loads(body)
                if not isinstance(metrics, dict):
                    raise ValueError("health JSON must be an object")
            health = metrics.get("health_ok", True)
            if not isinstance(health, bool):
                raise ValueError("health_ok must be boolean")
        except (http.client.HTTPException, TimeoutError, OSError):
            health = False
            logs.append(LogEntry("Local health probe failed; verify endpoint and process availability", "ERROR"))
        elapsed = round((time.monotonic() - started) * 1000, 2)
        return Sample(self.config.name, metrics.get("latency_ms", elapsed), metrics.get("error_rate", 0 if health else 1),
            metrics.get("cpu_pct"), metrics.get("memory_pct"), health_ok=health, logs=tuple(logs[-30:]))

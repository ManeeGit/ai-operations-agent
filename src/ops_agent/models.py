"""Validated telemetry boundary and privacy-preserving log normalization."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
import re


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


_SECRET = re.compile(r"(?i)(\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|token|authorization)\b\s*[=:]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)")
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")


def redact(value: str, limit: int = 1000) -> str:
    # Best effort, not a DLP guarantee. Bound processing before regular expressions.
    value = str(value)[:8192]
    value = _BEARER.sub("Bearer [REDACTED]", value)
    value = _SECRET.sub(lambda m: m.group(1) + "[REDACTED]", value)
    value = _EMAIL.sub("[EMAIL]", value)
    return value[:limit]


@dataclass(frozen=True)
class LogEntry:
    message: str
    level: str = "INFO"
    timestamp: str = field(default_factory=utcnow)

    def as_dict(self) -> dict:
        return {"timestamp": self.timestamp[:64], "level": self.level.upper()[:16], "message": redact(self.message)}


@dataclass(frozen=True)
class Sample:
    service: str
    latency_ms: float
    error_rate: float
    cpu_pct: float | None
    memory_pct: float | None
    health_ok: bool = True
    timestamp: str = field(default_factory=utcnow)
    logs: tuple[LogEntry, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.service, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", self.service):
            raise ValueError("service must be a short alphanumeric identifier")
        for name, low, high in (("latency_ms", 0, 3_600_000), ("error_rate", 0, 1), ("cpu_pct", 0, 100), ("memory_pct", 0, 100)):
            value = getattr(self, name)
            if value is None and name in ("cpu_pct", "memory_pct"):
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"invalid {name}")
        if not isinstance(self.health_ok, bool):
            raise ValueError("health_ok must be a boolean")
        if len(self.logs) > 30 or any(not isinstance(log, LogEntry) for log in self.logs):
            raise ValueError("logs must contain at most 30 LogEntry values")
        try:
            parsed = datetime.fromisoformat(self.timestamp)
        except (TypeError, ValueError) as exc:
            raise ValueError("timestamp must be ISO 8601") from exc
        if parsed.tzinfo is None:
            raise ValueError("timestamp must include timezone")

    def as_dict(self) -> dict:
        return {"service": self.service, "timestamp": self.timestamp, "latency_ms": self.latency_ms,
                "error_rate": self.error_rate, "cpu_pct": self.cpu_pct, "memory_pct": self.memory_pct,
                "health_ok": self.health_ok, "logs": [log.as_dict() for log in self.logs]}

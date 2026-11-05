"""Observe -> detect -> retrieve -> explain -> track lifecycle. No action executor."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4
from .detection import Detector
from .models import Sample, LogEntry, utcnow
from .storage import Store
from .triage import Triage


class Engine:
    def __init__(self, store: Store, triage: Triage | None = None, mode: str = "demo", recovery_samples: int = 3):
        if mode not in ("demo", "monitor") or not 1 <= recovery_samples <= 20:
            raise ValueError("invalid engine configuration")
        store.bind_mode(mode)
        self.store, self.triage, self.mode = store, triage or Triage(), mode
        self.detector = Detector()
        self.recovery_samples = recovery_samples
        self.recovery = defaultdict(int)
        self.lock = RLock()
        self.services = set()
        # Accepted reference windows persist independently of raw telemetry retention.
        states = self.store.detector_states()
        for service, state in states.items():
            self.services.add(service)
            self.detector.restore_state(service, state)
        if not states:
            for row in self.store.recent_samples():
                row["logs"] = tuple(LogEntry(**v) for v in row["logs"])
                sample = Sample(**row)
                self.services.add(sample.service)
                self.detector.inspect(sample)
            for service in self.services:
                self.store.save_detector_state(service, self.detector.export_state(service))
        self.store.event("agent_started", f"mode={mode}; model={'enabled' if self.triage.model else 'disabled'}; execution=disabled")

    def ingest(self, sample: Sample) -> list[dict]:
        with self.lock:
            if sample.service not in self.services and len(self.services) >= 64:
                raise ValueError("maximum tracked services reached")
            self.services.add(sample.service)
            self.store.save_sample(sample.as_dict())
            signals, abnormal = self.detector.inspect(sample)
            self.store.save_detector_state(sample.service, self.detector.export_state(sample.service))
            active = {i["kind"]: i for i in self.store.incidents(active=True) if i["service"] == sample.service}
            touched = []
            evidence = [log.as_dict() for log in sample.logs][-12:]
            for signal in signals:
                kind = signal["kind"]
                self.recovery[(sample.service, kind)] = 0
                if kind in active:
                    incident = active[kind]
                    incident["occurrences"] += 1
                    incident["signals"] = [signal]
                    incident["updated_at"] = sample.timestamp
                    incident["evidence"] = (incident["evidence"] + evidence)[-12:]
                    self.store.save_incident(incident)
                else:
                    diagnosis = self.triage.diagnose(kind, sample.service, [signal], evidence)
                    incident = {"id": uuid4().hex[:16], "service": sample.service, "kind": kind,
                        "severity": signal["severity"], "status": "open", "title": f"{sample.service}: elevated {kind}" if kind != "availability" else f"{sample.service}: health check failing",
                        "opened_at": sample.timestamp, "updated_at": sample.timestamp, "occurrences": 1,
                        "signals": [signal], "evidence": evidence, "diagnosis": diagnosis}
                    self.store.save_incident(incident, new=True)
                    self.store.event("incident_opened", f"{incident['id']} {sample.service}/{kind} source={diagnosis['source']}")
                touched.append(incident)
            for kind, incident in active.items():
                key = (sample.service, kind)
                if kind in abnormal:
                    self.recovery[key] = 0
                    continue
                self.recovery[key] += 1
                if self.recovery[key] >= self.recovery_samples:
                    incident["status"] = "resolved"
                    incident["updated_at"] = sample.timestamp
                    incident["resolved_at"] = sample.timestamp
                    self.store.save_incident(incident)
                    self.store.event("incident_resolved", f"{incident['id']} {sample.service}/{kind}: {self.recovery_samples} healthy samples")
                    touched.append(incident)
            return touched

    def acknowledge(self, incident_id: str) -> bool:
        with self.lock:
            for incident in self.store.incidents(active=True):
                if incident["id"] == incident_id:
                    if incident["status"] != "acknowledged":
                        incident["status"] = "acknowledged"
                        incident["updated_at"] = utcnow()
                        self.store.save_incident(incident)
                        self.store.event("incident_acknowledged", f"{incident_id}: local tracking only; no service action")
                    return True
            return False

    def overview(self) -> dict:
        incidents = self.store.incidents()
        active = [i for i in incidents if i["status"] != "resolved"]
        services = []
        for sample in self.store.latest_samples():
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(sample["timestamp"])).total_seconds()
            status = "unknown" if self.mode == "monitor" and age > 60 else "degraded" if any(i["service"] == sample["service"] for i in active) else "healthy"
            services.append({"name": sample["service"], "status": status,
                "last_seen": sample["timestamp"], **{k: sample[k] for k in ("latency_ms", "error_rate", "cpu_pct", "memory_pct")}})
        counts = self.store.counters()
        return {"mode": self.mode, "model": {"provider": "Ollama" if self.triage.model else "deterministic", "model": self.triage.model, "enabled": bool(self.triage.model)},
            "stats": {"samples": counts.get("samples", 0), "incidents_open": len(active), "incidents_total": counts.get("incidents", 0),
                "model_calls": self.triage.calls, "model_failures": self.triage.failures},
            "services": services, "incidents": incidents, "events": self.store.events(), "generated_at": utcnow()}

    def prometheus(self) -> str:
        stats = self.overview()["stats"]
        descriptions = {"samples": ("counter", "Observed telemetry samples"), "incidents_open": ("gauge", "Active incidents including acknowledged"),
            "incidents_total": ("counter", "Incidents opened since database creation"), "model_calls": ("counter", "Model calls this process"),
            "model_failures": ("counter", "Failed model calls this process")}
        lines = []
        for key, value in stats.items():
            name = "ops_agent_" + key + ("_total" if key in ("samples", "model_calls", "model_failures") else "")
            typ, description = descriptions[key]
            lines.extend([f"# HELP {name} {description}", f"# TYPE {name} {typ}", f"{name} {value}"])
        return "\n".join(lines) + "\n"

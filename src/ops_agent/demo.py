"""Seeded synthetic operations telemetry. Never contacts a real service."""
from __future__ import annotations

import random
from .engine import Engine
from .models import LogEntry, Sample

SCENARIOS = ("healthy", "latency", "errors", "memory", "cascade")
SERVICES = ("checkout-api", "inventory-worker", "payments-gateway")


def frame(rng: random.Random, scenario: str = "healthy") -> list[Sample]:
    if scenario not in SCENARIOS:
        raise ValueError("unknown demo scenario")
    samples = []
    for service in SERVICES:
        latency = round(rng.uniform(50, 100), 2)
        errors = round(rng.uniform(0, 0.008), 4)
        cpu, memory = round(rng.uniform(20, 34), 1), round(rng.uniform(37, 47), 1)
        healthy, logs = True, [LogEntry("Synthetic request batch completed")]
        if scenario in ("latency", "cascade") and service == "checkout-api":
            latency = round(rng.uniform(1100, 1500), 2)
            logs = [LogEntry("Synthetic connection pool queue grew; database request timeout after 1200ms", "WARN")]
        if scenario in ("errors", "cascade") and service == "payments-gateway":
            errors = round(rng.uniform(0.18, 0.23), 4)
            logs = [LogEntry("Synthetic upstream dependency returned 503; payment authorization failed", "ERROR")]
        if scenario in ("memory", "cascade") and service == "inventory-worker":
            memory = round(rng.uniform(94, 98), 1)
            logs = [LogEntry("Synthetic heap allocation increased; repeated GC pause observed", "WARN")]
        samples.append(Sample(service, latency, errors, cpu, memory, healthy, logs=tuple(logs)))
    return samples


def seed(engine: Engine, rng: random.Random) -> None:
    for _ in range(12):
        for sample in frame(rng):
            engine.ingest(sample)


def inject(engine: Engine, scenario: str, rng: random.Random) -> dict:
    if scenario not in SCENARIOS:
        raise ValueError("unknown demo scenario")
    for _ in range(4):
        for sample in frame(rng, scenario):
            engine.ingest(sample)
    engine.store.event("demo_scenario", f"Synthetic scenario={scenario}; no external systems contacted")
    return engine.overview()

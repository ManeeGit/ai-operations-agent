"""Robust, bounded streaming baselines plus absolute operational guardrails."""
from __future__ import annotations

from collections import defaultdict, deque
from statistics import median
from .models import Sample

# metric -> (absolute limit, minimum deviation, minimum ratio, severity)
RULES = {
    "latency_ms": (2000.0, 150.0, 2.5, "warning"),
    "error_rate": (0.10, 0.03, 3.0, "critical"),
    "cpu_pct": (95.0, 25.0, 1.7, "warning"),
    "memory_pct": (92.0, 20.0, 1.5, "warning"),
}
KINDS = {"latency_ms": "latency", "error_rate": "errors", "cpu_pct": "cpu", "memory_pct": "memory", "health_ok": "availability"}


class Detector:
    def __init__(self, window: int = 60, warmup: int = 8, confirmations: int = 2):
        if not 3 <= warmup <= window <= 1000 or not 1 <= confirmations <= 10:
            raise ValueError("invalid detector bounds")
        self.window, self.warmup, self.confirmations = window, warmup, confirmations
        self.history: dict[tuple[str, str], deque] = defaultdict(lambda: deque(maxlen=window))
        self.streak: dict[tuple[str, str], int] = defaultdict(int)

    def inspect(self, sample: Sample) -> tuple[list[dict], set[str]]:
        """Return confirmed signals and all currently abnormal kinds.

        Unconfirmed anomalies never enter their metric's reference distribution.
        Absolute guardrails apply even before a baseline is available.
        """
        confirmed, abnormal = [], set()
        for metric, (absolute, floor, ratio, severity) in RULES.items():
            key = (sample.service, metric)
            observed = getattr(sample, metric)
            if observed is None:
                # Missing resource metrics neither train a baseline nor resolve incidents.
                self.streak[key] = 0
                abnormal.add(KINDS[metric])
                continue
            value = float(observed)
            hist = self.history[key]
            center = median(hist) if hist else value
            threshold = absolute
            baseline_ready = len(hist) >= self.warmup
            if baseline_ready:
                mad = median(abs(v - center) for v in hist)
                adaptive = max(center + max(6 * 1.4826 * mad, floor), center * ratio)
                threshold = min(absolute, adaptive)
            bad = value > threshold
            self.streak[key] = self.streak[key] + 1 if bad else 0
            if bad:
                abnormal.add(KINDS[metric])
                if self.streak[key] >= self.confirmations:
                    confirmed.append({"name": metric, "kind": KINDS[metric], "value": value,
                        "baseline": round(center, 3), "threshold": round(threshold, 3), "severity": severity,
                        "explanation": f"{metric} exceeded {'robust baseline / absolute guardrail' if baseline_ready else 'absolute guardrail during warmup'} for {self.streak[key]} samples"})
            else:
                hist.append(value)
        key = (sample.service, "health_ok")
        self.streak[key] = self.streak[key] + 1 if not sample.health_ok else 0
        if not sample.health_ok:
            abnormal.add("availability")
            if self.streak[key] >= self.confirmations:
                confirmed.append({"name": "health_ok", "kind": "availability", "value": 0,
                    "baseline": 1, "threshold": 1, "severity": "critical", "explanation": "Health check failed in consecutive samples"})
        return confirmed, abnormal

    def export_state(self, service: str) -> dict:
        return {"history": {metric: list(self.history[(service, metric)]) for metric in RULES},
                "streak": {metric: self.streak[(service, metric)] for metric in (*RULES, "health_ok")}}

    def restore_state(self, service: str, state: dict) -> None:
        # State is local application data; validate before adopting reference values.
        Sample(service, 0, 0, 0, 0)
        for metric, values in state["history"].items():
            if metric not in RULES or not isinstance(values, list) or len(values) > self.window:
                raise ValueError("invalid persisted baseline")
            for value in values:
                Sample(**{"service": service, "latency_ms": 0, "error_rate": 0, "cpu_pct": 0, "memory_pct": 0, metric: value})
            self.history[(service, metric)].extend(values)
        for metric, streak in state["streak"].items():
            if metric not in (*RULES, "health_ok") or not isinstance(streak, int) or streak < 0:
                raise ValueError("invalid persisted detector streak")
            self.streak[(service, metric)] = streak

"""Bounded SQLite persistence. One connection guarded across HTTP/polling threads."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from threading import RLock
from .models import redact, utcnow


class Store:
    def __init__(self, path: str = ":memory:"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.lock = RLock()
        with self.connection:
            self.connection.executescript("""
              PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS samples (id INTEGER PRIMARY KEY, service TEXT NOT NULL, timestamp TEXT NOT NULL, data TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS samples_service ON samples(service, id);
              CREATE TABLE IF NOT EXISTS incidents (id TEXT PRIMARY KEY, service TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL, updated_at TEXT NOT NULL, data TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS incidents_active ON incidents(service, kind, status);
              CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, event TEXT NOT NULL, detail TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS detector_states (service TEXT PRIMARY KEY, data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
              PRAGMA user_version=2;
            """)

    def detector_states(self) -> dict:
        with self.lock:
            return {r["service"]: json.loads(r["data"]) for r in self.connection.execute("SELECT service, data FROM detector_states")}

    def save_detector_state(self, service: str, state: dict):
        with self.lock, self.connection:
            self.connection.execute("INSERT INTO detector_states VALUES (?,?) ON CONFLICT(service) DO UPDATE SET data=excluded.data", (service, json.dumps(state)))

    def bind_mode(self, mode: str):
        with self.lock, self.connection:
            previous = self.connection.execute("SELECT value FROM metadata WHERE name='mode'").fetchone()
            if previous and previous[0] != mode:
                raise ValueError("database mode mismatch; use separate demo and monitor databases")
            self.connection.execute("INSERT OR IGNORE INTO metadata VALUES ('mode', ?)", (mode,))

    def close(self):
        with self.lock:
            self.connection.close()

    def bump(self, name: str):
        with self.lock, self.connection:
            self.connection.execute("INSERT INTO counters VALUES (?,1) ON CONFLICT(name) DO UPDATE SET value=value+1", (name,))

    def counters(self) -> dict:
        with self.lock:
            return {r["name"]: r["value"] for r in self.connection.execute("SELECT * FROM counters")}

    def save_sample(self, sample: dict):
        with self.lock, self.connection:
            self.connection.execute("INSERT INTO samples(service,timestamp,data) VALUES (?,?,?)", (sample["service"], sample["timestamp"], json.dumps(sample)))
            self.connection.execute("INSERT INTO counters VALUES ('samples',1) ON CONFLICT(name) DO UPDATE SET value=value+1")
            # Bounded row counts; SQLite reuses freed pages (file size high-water mark).
            self.connection.execute("DELETE FROM samples WHERE id NOT IN (SELECT id FROM samples ORDER BY id DESC LIMIT 2000)")

    def recent_samples(self, limit: int = 1000) -> list[dict]:
        with self.lock:
            rows = self.connection.execute("SELECT data FROM samples ORDER BY id DESC LIMIT ?", (min(limit, 2000),)).fetchall()
            return [json.loads(r[0]) for r in reversed(rows)]

    def latest_samples(self) -> list[dict]:
        with self.lock:
            rows = self.connection.execute("SELECT data FROM samples WHERE id IN (SELECT MAX(id) FROM samples GROUP BY service) ORDER BY service").fetchall()
            return [json.loads(r[0]) for r in rows]

    def save_incident(self, incident: dict, new: bool = False):
        with self.lock, self.connection:
            self.connection.execute("INSERT INTO incidents VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at, data=excluded.data",
                (incident["id"], incident["service"], incident["kind"], incident["status"], incident["updated_at"], json.dumps(incident)))
            if new:
                self.connection.execute("INSERT INTO counters VALUES ('incidents',1) ON CONFLICT(name) DO UPDATE SET value=value+1")
            # Never silently discard open incidents. Service/kind cap bounds them.
            self.connection.execute("DELETE FROM incidents WHERE status='resolved' AND id NOT IN (SELECT id FROM incidents ORDER BY updated_at DESC LIMIT 200)")

    def incidents(self, active: bool = False) -> list[dict]:
        with self.lock:
            where = " WHERE status != 'resolved'" if active else ""
            rows = self.connection.execute("SELECT data FROM incidents" + where + " ORDER BY updated_at DESC").fetchall()
            return [json.loads(r[0]) for r in rows]

    def event(self, event: str, detail: str):
        with self.lock, self.connection:
            self.connection.execute("INSERT INTO events(timestamp,event,detail) VALUES (?,?,?)", (utcnow(), event[:80], redact(detail)))
            self.connection.execute("DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 1000)")

    def events(self, limit: int = 30) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.connection.execute("SELECT timestamp,event,detail FROM events ORDER BY id DESC LIMIT ?", (limit,))]

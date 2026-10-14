"""Atomic, idempotent SQLite ingestion with explicit provenance."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3

from .junit import parse_junit

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(version INTEGER NOT NULL);
INSERT INTO meta SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM meta);
CREATE TABLE IF NOT EXISTS reports(
  run_id TEXT NOT NULL, shard TEXT NOT NULL, revision TEXT NOT NULL,
  environment TEXT NOT NULL, digest TEXT NOT NULL,
  PRIMARY KEY(run_id, shard)
);
CREATE TABLE IF NOT EXISTS observations(
  run_id TEXT NOT NULL, shard TEXT NOT NULL, suite TEXT NOT NULL,
  classname TEXT NOT NULL, name TEXT NOT NULL, attempt INTEGER NOT NULL,
  status TEXT NOT NULL, duration REAL NOT NULL, message TEXT NOT NULL,
  PRIMARY KEY(run_id, shard, suite, classname, name, attempt),
  FOREIGN KEY(run_id, shard) REFERENCES reports(run_id, shard)
);
"""


class Store:
    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript(SCHEMA)
        versions = [r[0] for r in self.db.execute("SELECT version FROM meta")]
        if versions != [1]:
            self.db.close()
            raise ValueError("Unsupported Faultline database schema")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.db.close()

    def ingest(self, path: str | Path, *, run_id: str, revision: str,
               environment: str = "default", shard: str = "default") -> int:
        for label, value in (("run_id", run_id), ("revision", revision), ("environment", environment), ("shard", shard)):
            if not value.strip():
                raise ValueError(f"{label} cannot be empty")
        rows = parse_junit(path)
        digest = hashlib.sha256(json.dumps([asdict(r) for r in rows], sort_keys=True, ensure_ascii=True).encode()).hexdigest()
        with self.db:
            # Lock before checking: concurrent writers cannot race the provenance checks.
            self.db.execute("BEGIN IMMEDIATE")
            existing = self.db.execute("SELECT * FROM reports WHERE run_id=? AND shard=?", (run_id, shard)).fetchone()
            if existing:
                if (existing["revision"], existing["environment"], existing["digest"]) != (revision, environment, digest):
                    raise ValueError("Run/shard already exists with different content or provenance")
                return 0
            other = self.db.execute("SELECT revision, environment FROM reports WHERE run_id=? LIMIT 1", (run_id,)).fetchone()
            if other and (other["revision"], other["environment"]) != (revision, environment):
                raise ValueError("All shards in a run must share revision and environment")
            self.db.execute("INSERT INTO reports VALUES(?,?,?,?,?)", (run_id, shard, revision, environment, digest))
            self.db.executemany("INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?)", [(run_id, shard, r.suite, r.classname, r.name, r.attempt, r.status, r.duration, r.message) for r in rows])
        return len(rows)

    def observations(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("""
            SELECT o.*, r.revision, r.environment FROM observations o
            JOIN reports r USING(run_id, shard)
            ORDER BY o.suite, o.classname, o.name, r.environment, o.run_id, o.shard, o.attempt
        """)]

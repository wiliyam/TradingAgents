"""Persistent single-owner job queue. All SQL values are bound parameters."""

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / "dashboard.sqlite3"
        with self.connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, symbol TEXT NOT NULL, day TEXT NOT NULL,
                    mode TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL,
                    result TEXT, error TEXT);
                CREATE TABLE IF NOT EXISTS progress (
                    job_id TEXT NOT NULL, name TEXT NOT NULL, content TEXT NOT NULL,
                    updated REAL NOT NULL, PRIMARY KEY(job_id,name));
                CREATE TABLE IF NOT EXISTS notifications (
                    job_id TEXT PRIMARY KEY, status TEXT NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS integrations (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT);
                CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT);
                CREATE TABLE IF NOT EXISTS attempts (ip TEXT, created REAL);
                CREATE INDEX IF NOT EXISTS attempts_ip ON attempts(ip, created);
            """)
        os.chmod(self.path, 0o600)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def settings(self):
        with self.connection() as db:
            row = db.execute("SELECT value FROM settings WHERE id=1").fetchone()
        return (
            json.loads(row[0])
            if row
            else {
                "provider": "openai",
                "quick_model": "gpt-5.6-luna",
                "deep_model": "gpt-5.6-luna",
                "api_key": "",
            }
        )

    def save_settings(self, value):
        with self.connection() as db:
            db.execute(
                "INSERT OR REPLACE INTO settings(id,value) VALUES(1,?)", (json.dumps(value),)
            )

    def enqueue(self, symbol, day, mode):
        job_id = uuid.uuid4().hex
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM jobs WHERE status IN ('queued','running')").fetchone():
                raise ValueError("An analysis is already queued or running. Wait for it to finish.")
            if (
                db.execute(
                    "SELECT COUNT(*) FROM jobs WHERE created>?", (time.time() - 86400,)
                ).fetchone()[0]
                >= 24
            ):
                raise ValueError("Daily limit reached: 24 analyses per day.")
            db.execute(
                "INSERT INTO jobs VALUES(?,?,?,?,?,?,NULL,NULL)",
                (job_id, symbol, day, mode, "queued", time.time()),
            )
        return job_id

    def claim(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1"
            ).fetchone()
            if row:
                db.execute("UPDATE jobs SET status='running' WHERE id=?", (row["id"],))
                return dict(row)
        return None

    def finish(self, job_id, result=None, error=None):
        with self.connection() as db:
            db.execute(
                "UPDATE jobs SET status=?,result=?,error=? WHERE id=?",
                (
                    "failed" if error else "complete",
                    json.dumps(result) if result is not None else None,
                    error,
                    job_id,
                ),
            )

    def progress(self, job_id, fields):
        with self.connection() as db:
            for name, content in fields.items():
                encoded = json.dumps(content)
                db.execute(
                    "INSERT INTO progress VALUES(?,?,?,?) ON CONFLICT(job_id,name) DO UPDATE SET content=excluded.content,updated=excluded.updated WHERE progress.content != excluded.content",
                    (job_id, name, encoded, time.time()),
                )

    def telegram(self):
        with self.connection() as db:
            row = db.execute("SELECT value FROM integrations WHERE id=1").fetchone()
        return json.loads(row[0]) if row else {"token": "", "channel": "", "enabled": False}

    def save_telegram(self, value):
        with self.connection() as db:
            db.execute("INSERT OR REPLACE INTO integrations VALUES(1,?)", (json.dumps(value),))

    def notification(self, job_id, status):
        with self.connection() as db:
            db.execute(
                "INSERT OR REPLACE INTO notifications VALUES(?,?,?)", (job_id, status, time.time())
            )

    def recover(self):
        with self.connection() as db:
            db.execute(
                "UPDATE jobs SET status='failed',error='Analysis interrupted by a service restart. Please run again.' WHERE status='running'"
            )

    def job(self, job_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return None
        value = dict(row)
        value["result"] = json.loads(value["result"]) if value["result"] else None
        with self.connection() as db:
            value["progress"] = {
                r["name"]: {"content": json.loads(r["content"]), "updated": r["updated"]}
                for r in db.execute("SELECT * FROM progress WHERE job_id=?", (job_id,))
            }
            delivery = db.execute(
                "SELECT status,updated FROM notifications WHERE job_id=?", (job_id,)
            ).fetchone()
            value["notification"] = dict(delivery) if delivery else None
        return value

    def jobs(self):
        with self.connection() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT id,symbol,day,mode,status,created FROM jobs ORDER BY created DESC LIMIT 100"
                )
            ]

    def login_attempt(self, ip, record=False, clear=False):
        now = time.time()
        with self.connection() as db:
            db.execute("DELETE FROM attempts WHERE created<?", (now - 900,))
            if clear:
                db.execute("DELETE FROM attempts WHERE ip=?", (ip,))
            if record:
                db.execute("INSERT INTO attempts VALUES(?,?)", (ip, now))
            return db.execute("SELECT COUNT(*) FROM attempts WHERE ip=?", (ip,)).fetchone()[0]

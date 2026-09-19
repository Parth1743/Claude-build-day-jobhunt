"""SQLite connection and schema."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone

from . import config

LEDGER_KINDS = ("experience", "education", "skill", "certification", "project", "achievement")
SKILL_LEVELS = ("beginner", "intermediate", "advanced", "expert")
JOB_STATUSES = ("saved", "applied", "screening", "interview", "offer", "rejected", "withdrawn")
ROADMAP_STATUSES = ("todo", "in_progress", "done", "skipped")

SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger_entries (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    org TEXT,
    start_date TEXT,
    end_date TEXT,
    description TEXT,
    skills TEXT NOT NULL DEFAULT '[]',
    level TEXT,
    url TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ledger_events (
    id INTEGER PRIMARY KEY,
    entry_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    source TEXT,
    snapshot TEXT NOT NULL,
    at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS target_roles (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL UNIQUE,
    description TEXT,
    required_skills TEXT NOT NULL DEFAULT '[]',
    nice_to_have TEXT NOT NULL DEFAULT '[]',
    priority INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    location TEXT,
    role_id INTEGER REFERENCES target_roles(id),
    jd_text TEXT,
    status TEXT NOT NULL DEFAULT 'saved',
    fit_score INTEGER,
    analysis TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    applied_at TEXT
);

CREATE TABLE IF NOT EXISTS job_events (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    note TEXT,
    at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS materials (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS discovered_jobs (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT,
    location TEXT,
    remote INTEGER NOT NULL DEFAULT 0,
    url TEXT NOT NULL,
    description TEXT,
    tags TEXT NOT NULL DEFAULT '[]',
    salary TEXT,
    publisher TEXT,
    posted_at TEXT,
    query TEXT,
    role_id INTEGER,
    match_score INTEGER NOT NULL DEFAULT 0,
    matched_skills TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'new',
    saved_job_id INTEGER,
    first_seen_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    UNIQUE(source, external_id)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS roadmap_items (
    id INTEGER PRIMARY KEY,
    role_id INTEGER NOT NULL,
    skill TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 1,
    why TEXT,
    actions TEXT NOT NULL DEFAULT '[]',
    resources TEXT NOT NULL DEFAULT '[]',
    est_weeks REAL,
    status TEXT NOT NULL DEFAULT 'todo',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


_init_lock = threading.Lock()
_initialized: set[str] = set()


def connect() -> sqlite3.Connection:
    """Open a connection safe for use across worker threads and concurrent users.

    check_same_thread=False lets FastAPI hand the connection between its thread
    pool workers (each request still owns exactly one connection). WAL mode lets
    readers and a writer proceed at the same time, and busy_timeout makes
    concurrent writers wait instead of failing with "database is locked".

    Schema creation and the WAL switch need exclusive access, and SQLite does
    not apply the busy timeout to them, so they run once per process under a
    lock instead of on every connection.
    """
    path = config.db_path()
    key = str(path)
    if key in _initialized and not path.exists():
        _initialized.discard(key)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    if key not in _initialized:
        with _init_lock:
            if key not in _initialized:
                conn.execute("PRAGMA journal_mode = WAL")
                conn.executescript(SCHEMA)
                _initialized.add(key)
    return conn


class Pool:
    """Keep a few connections open between requests.

    Never blocks: if no idle connection is available a fresh one is opened, and
    surplus connections are closed on release. Keeping connections alive also
    keeps the WAL file alive, which avoids the checkpoint-and-delete churn that
    causes lock stalls on Windows when every request opens and closes its own.
    """

    def __init__(self, max_idle: int = 8):
        self.max_idle = max_idle
        self._idle: list[sqlite3.Connection] = []
        self._lock = threading.Lock()
        self._path: str | None = None

    def acquire(self) -> sqlite3.Connection:
        path = str(config.db_path())
        with self._lock:
            if self._path != path:  # database location changed (tests, config)
                for c in self._idle:
                    c.close()
                self._idle.clear()
                self._path = path
            if self._idle:
                return self._idle.pop()
        return connect()

    def release(self, conn: sqlite3.Connection) -> None:
        try:
            conn.rollback()  # drop any half-finished transaction
        except sqlite3.Error:
            conn.close()
            return
        with self._lock:
            if len(self._idle) < self.max_idle and self._path == str(config.db_path()):
                self._idle.append(conn)
                return
        conn.close()

    def close_all(self) -> None:
        with self._lock:
            for c in self._idle:
                c.close()
            self._idle.clear()


pool = Pool()


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def loads(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None

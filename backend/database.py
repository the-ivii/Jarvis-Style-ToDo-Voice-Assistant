"""SQLite setup for todos and memory stores."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from . import config


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def todos_conn():
    conn = _connect(config.TODOS_DB)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


@contextmanager
def memory_conn():
    conn = _connect(config.MEMORY_DB)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if they don't exist yet."""
    with todos_conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS todos (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                task        TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'pending',
                priority    TEXT NOT NULL DEFAULT 'medium',
                due_date    TEXT,
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )

    with memory_conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                content     TEXT NOT NULL,
                category    TEXT NOT NULL DEFAULT 'general',
                embedding   BLOB,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )

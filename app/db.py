"""Thin SQLite access layer.

SQLite keeps the MVP dependency-free; every query is written in plain SQL so the
same statements port to Postgres later with minimal edits.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from .config import BASE_DIR, settings

_local = threading.local()
_write_lock = threading.RLock()


# --------------------------------------------------------------------------- #
# time helpers
# --------------------------------------------------------------------------- #
def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def today() -> date:
    return datetime.now(timezone.utc).date()


def today_iso() -> str:
    return today().isoformat()


def parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# connection handling
# --------------------------------------------------------------------------- #
def _connect() -> sqlite3.Connection:
    path = Path(settings.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _connect()
        _local.conn = conn
    return conn


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    """Serialised write transaction. SQLite allows a single writer; the lock
    turns lock contention into a queue instead of 'database is locked'."""
    conn = get_conn()
    with _write_lock:
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


# --------------------------------------------------------------------------- #
# query helpers
# --------------------------------------------------------------------------- #
def query(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    return list(get_conn().execute(sql, tuple(params)).fetchall())


def query_one(sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    return get_conn().execute(sql, tuple(params)).fetchone()


def scalar(sql: str, params: Iterable[Any] = (), default: Any = 0) -> Any:
    row = query_one(sql, params)
    if row is None:
        return default
    value = row[0]
    return default if value is None else value


def execute(sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
    with tx() as conn:
        return conn.execute(sql, tuple(params))


def insert(table: str, data: dict[str, Any]) -> None:
    cols = ", ".join(data)
    marks = ", ".join("?" for _ in data)
    execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(data.values()))


def update(table: str, row_id: str, data: dict[str, Any], id_column: str = "id") -> None:
    if not data:
        return
    sets = ", ".join(f"{k} = ?" for k in data)
    execute(
        f"UPDATE {table} SET {sets} WHERE {id_column} = ?",
        [*data.values(), row_id],
    )


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def loads(value: Any, default: Any = None) -> Any:
    if value in (None, ""):
        return {} if default is None else default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {} if default is None else default


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


# --------------------------------------------------------------------------- #
# id generation
# --------------------------------------------------------------------------- #
def next_sequence(name: str, start: int = 1) -> int:
    """Atomically bump a named counter. Must be called inside or outside a tx;
    it opens its own short transaction when not already in one."""
    conn = get_conn()
    with _write_lock:
        in_tx = conn.in_transaction
        if not in_tx:
            conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                "INSERT INTO sequences (name, value) VALUES (?, ?) "
                "ON CONFLICT(name) DO UPDATE SET value = value + 1",
                (name, start),
            )
            value = conn.execute(
                "SELECT value FROM sequences WHERE name = ?", (name,)
            ).fetchone()[0]
            if not in_tx:
                conn.commit()
            return int(value)
        except Exception:
            if not in_tx:
                conn.rollback()
            raise


def new_id(prefix: str, sequence: str | None = None, width: int = 5, start: int = 10000) -> str:
    return f"{prefix}-{next_sequence(sequence or prefix, start):0{width}d}"


# --------------------------------------------------------------------------- #
# migrations
# --------------------------------------------------------------------------- #
#: Columns added after the first release. `CREATE TABLE IF NOT EXISTS` cannot
#: alter an existing table, so new columns are applied additively here.
_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("customers", "status_token", "TEXT"),
    ("conversations", "live_cursor", "TEXT"),
)


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, decl in _ADDED_COLUMNS:
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if not existing:            # table not created yet
            continue
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_status_token "
        "ON customers(status_token) WHERE status_token IS NOT NULL"
    )


def init_db() -> None:
    schema = (BASE_DIR / "schema.sql").read_text(encoding="utf-8")
    conn = get_conn()
    with _write_lock:
        conn.executescript(schema)
        _migrate(conn)
        conn.commit()


def reset_db() -> None:
    """Drop everything and recreate. Used by the test suite."""
    conn = get_conn()
    with _write_lock:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        conn.execute("PRAGMA foreign_keys = OFF")
        for name in tables:
            conn.execute(f"DROP TABLE IF EXISTS {name}")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()
    init_db()


def close_conn() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None

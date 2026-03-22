"""SQLite persistence layer: upsert records and track sync cursors."""

import json
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _ensure_sync_meta(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS _sync_meta (
            source TEXT PRIMARY KEY,
            last_cursor TEXT,
            last_run_at TEXT NOT NULL DEFAULT (datetime('now')),
            total_upserted INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.commit()


def upsert_records(
    db_path: str,
    table: str,
    records: list[dict],
) -> int:
    """
    Upsert a list of flat dicts into `table`.
    Creates the table dynamically on first insert.
    Returns the number of rows affected.
    """
    if not records:
        return 0

    conn = _connect(db_path)
    try:
        # Collect all column names across all records
        columns: list[str] = list({col for rec in records for col in rec.keys()})
        col_defs = ", ".join(f'"{c}" TEXT' for c in columns)

        conn.execute(
            f'CREATE TABLE IF NOT EXISTS "{table}" (_row_id INTEGER PRIMARY KEY AUTOINCREMENT, {col_defs})'
        )

        placeholders = ", ".join(f'"{c}"' for c in columns)
        values_ph = ", ".join("?" for _ in columns)
        sql = f'INSERT OR REPLACE INTO "{table}" ({placeholders}) VALUES ({values_ph})'

        rows = []
        for rec in records:
            row = []
            for col in columns:
                val = rec.get(col)
                if isinstance(val, (dict, list)):
                    val = json.dumps(val)
                row.append(val)
            rows.append(row)

        conn.executemany(sql, rows)
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def save_cursor(db_path: str, source: str, cursor: str | None, upserted: int) -> None:
    conn = _connect(db_path)
    try:
        _ensure_sync_meta(conn)
        conn.execute(
            """
            INSERT INTO _sync_meta (source, last_cursor, last_run_at, total_upserted)
            VALUES (?, ?, datetime('now'), ?)
            ON CONFLICT(source) DO UPDATE SET
                last_cursor = excluded.last_cursor,
                last_run_at = excluded.last_run_at,
                total_upserted = _sync_meta.total_upserted + excluded.total_upserted
            """,
            (source, cursor, upserted),
        )
        conn.commit()
    finally:
        conn.close()


def load_cursor(db_path: str, source: str) -> str | None:
    conn = _connect(db_path)
    try:
        _ensure_sync_meta(conn)
        row = conn.execute(
            "SELECT last_cursor FROM _sync_meta WHERE source = ?", (source,)
        ).fetchone()
        return row["last_cursor"] if row else None
    finally:
        conn.close()


def query_table(db_path: str, table: str, limit: int = 20) -> list[dict]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            f'SELECT * FROM "{table}" LIMIT ?', (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def get_sync_status(db_path: str) -> list[dict]:
    conn = _connect(db_path)
    try:
        _ensure_sync_meta(conn)
        rows = conn.execute("SELECT * FROM _sync_meta ORDER BY last_run_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

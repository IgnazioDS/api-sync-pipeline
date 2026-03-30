"""SQLite persistence layer: upsert records and track sync cursors."""

import json
import logging
import sqlite3

logger = logging.getLogger(__name__)


class StorageError(RuntimeError):
    """Raised when SQLite operations fail."""


def _connect(db_path: str) -> sqlite3.Connection:
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
    except sqlite3.Error as exc:
        raise StorageError(f"Could not open database '{db_path}': {exc}") from exc


def _ensure_sync_meta(conn: sqlite3.Connection) -> None:
    try:
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
    except sqlite3.Error as exc:
        raise StorageError(f"Failed to initialize sync metadata table: {exc}") from exc


def _quote_identifier(identifier: str) -> str:
    if not identifier or not identifier.strip():
        raise StorageError("SQL identifiers must not be empty")
    return '"' + identifier.replace('"', '""') + '"'


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _get_table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    table_ref = _quote_identifier(table)
    rows = conn.execute(f"PRAGMA table_info({table_ref})").fetchall()
    return {row["name"] for row in rows}


def _has_unique_key(conn: sqlite3.Connection, table: str, id_field: str) -> bool:
    table_ref = _quote_identifier(table)
    for index in conn.execute(f"PRAGMA index_list({table_ref})").fetchall():
        if not index["unique"]:
            continue
        index_name = _quote_identifier(index["name"])
        columns = conn.execute(f"PRAGMA index_info({index_name})").fetchall()
        if [column["name"] for column in columns] == [id_field]:
            return True
    return False


def _deduplicate_rows(conn: sqlite3.Connection, table: str, id_field: str) -> None:
    table_ref = _quote_identifier(table)
    id_ref = _quote_identifier(id_field)
    conn.execute(
        f"""
        DELETE FROM {table_ref}
        WHERE {id_ref} IS NOT NULL
          AND rowid NOT IN (
              SELECT MAX(rowid)
              FROM {table_ref}
              WHERE {id_ref} IS NOT NULL
              GROUP BY {id_ref}
          )
        """
    )


def _ensure_table_schema(
    conn: sqlite3.Connection,
    table: str,
    id_field: str,
    records: list[dict],
) -> list[str]:
    table_ref = _quote_identifier(table)
    wanted_columns = {column for record in records for column in record.keys()}
    if id_field not in wanted_columns:
        raise StorageError(f"Primary key field '{id_field}' must be present in every record batch")

    ordered_columns = [id_field] + sorted(wanted_columns - {id_field})

    if not _table_exists(conn, table):
        column_defs = [f"{_quote_identifier(id_field)} TEXT PRIMARY KEY"]
        column_defs.extend(f"{_quote_identifier(column)} TEXT" for column in ordered_columns if column != id_field)
        conn.execute(f"CREATE TABLE {table_ref} ({', '.join(column_defs)})")
        return ordered_columns

    existing_columns = _get_table_columns(conn, table)
    missing_columns = [column for column in ordered_columns if column not in existing_columns]
    for column in missing_columns:
        conn.execute(f"ALTER TABLE {table_ref} ADD COLUMN {_quote_identifier(column)} TEXT")

    if not _has_unique_key(conn, table, id_field):
        _deduplicate_rows(conn, table, id_field)
        index_name = _quote_identifier(f"uq_{table}_{id_field}")
        conn.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} ON {table_ref} ({_quote_identifier(id_field)})"
        )

    return ordered_columns


def upsert_records(
    db_path: str,
    table: str,
    records: list[dict],
    id_field: str = "id",
) -> int:
    """Upsert a list of dicts into `table` and return the number of rows processed."""
    if not records:
        return 0

    conn = _connect(db_path)
    try:
        columns = _ensure_table_schema(conn, table, id_field, records)
        table_ref = _quote_identifier(table)
        column_list = ", ".join(_quote_identifier(column) for column in columns)
        values_ph = ", ".join("?" for _ in columns)
        update_columns = [column for column in columns if column != id_field]

        if update_columns:
            updates = ", ".join(
                f"{_quote_identifier(column)} = excluded.{_quote_identifier(column)}"
                for column in update_columns
            )
            sql = (
                f"INSERT INTO {table_ref} ({column_list}) VALUES ({values_ph}) "
                f"ON CONFLICT ({_quote_identifier(id_field)}) DO UPDATE SET {updates}"
            )
        else:
            sql = (
                f"INSERT INTO {table_ref} ({column_list}) VALUES ({values_ph}) "
                f"ON CONFLICT ({_quote_identifier(id_field)}) DO NOTHING"
            )

        rows = []
        for rec in records:
            if rec.get(id_field) in (None, ""):
                raise StorageError(f"Record is missing required id field '{id_field}'")
            row = []
            for col in columns:
                val = rec.get(col)
                if isinstance(val, (dict, list)):
                    val = json.dumps(val)
                elif col == id_field and val is not None:
                    val = str(val)
                row.append(val)
            rows.append(row)

        conn.executemany(sql, rows)
        conn.commit()
        return len(rows)
    except sqlite3.Error as exc:
        raise StorageError(f"Failed to upsert records into '{table}': {exc}") from exc
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
    except sqlite3.Error as exc:
        raise StorageError(f"Failed to save sync cursor for '{source}': {exc}") from exc
    finally:
        conn.close()


def load_cursor(db_path: str, source: str) -> str | None:
    conn = _connect(db_path)
    try:
        _ensure_sync_meta(conn)
        row = conn.execute(
            "SELECT last_cursor FROM _sync_meta WHERE source = ?",
            (source,),
        ).fetchone()
        return row["last_cursor"] if row else None
    except sqlite3.Error as exc:
        raise StorageError(f"Failed to load sync cursor for '{source}': {exc}") from exc
    finally:
        conn.close()


def query_table(db_path: str, table: str, limit: int = 20) -> list[dict]:
    conn = _connect(db_path)
    try:
        table_ref = _quote_identifier(table)
        rows = conn.execute(
            f"SELECT * FROM {table_ref} ORDER BY rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return []
        raise StorageError(f"Failed to query table '{table}': {exc}") from exc
    except sqlite3.Error as exc:
        raise StorageError(f"Failed to query table '{table}': {exc}") from exc
    finally:
        conn.close()


def get_sync_status(db_path: str) -> list[dict]:
    conn = _connect(db_path)
    try:
        _ensure_sync_meta(conn)
        rows = conn.execute("SELECT * FROM _sync_meta ORDER BY last_run_at DESC").fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error as exc:
        raise StorageError(f"Failed to fetch sync status: {exc}") from exc
    finally:
        conn.close()

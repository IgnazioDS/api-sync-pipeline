"""Tests for the SQLite storage layer."""

import json
import os
import sqlite3
import tempfile
from unittest.mock import patch

import pytest

from api_sync.storage import (
    StorageError,
    get_sync_status,
    load_cursor,
    query_table,
    save_cursor,
    upsert_records,
)


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    os.unlink(path)


class TestUpsertRecords:
    def test_inserts_flat_records(self, db):
        n = upsert_records(db, "users", [{"id": "1", "name": "Alice"}])
        assert n == 1
        rows = query_table(db, "users")
        assert rows[0]["name"] == "Alice"

    def test_replaces_on_duplicate(self, db):
        upsert_records(db, "users", [{"id": "1", "name": "Alice"}])
        upsert_records(db, "users", [{"id": "1", "name": "Bob"}])
        rows = query_table(db, "users")
        assert len(rows) == 1
        assert rows[0]["name"] == "Bob"

    def test_nested_dict_serialized_to_json(self, db):
        upsert_records(db, "items", [{"id": "1", "meta": {"x": 1}}])
        rows = query_table(db, "items")
        assert json.loads(rows[0]["meta"]) == {"x": 1}

    def test_multiple_records_in_one_call(self, db):
        records = [{"id": str(i), "val": i} for i in range(10)]
        n = upsert_records(db, "batch", records)
        assert n == 10

    def test_empty_list_returns_zero(self, db):
        n = upsert_records(db, "empty_table", [])
        assert n == 0

    def test_sparse_records_different_columns(self, db):
        upsert_records(db, "sparse", [{"id": "1", "a": "x"}, {"id": "2", "b": "y"}])
        rows = query_table(db, "sparse", limit=10)
        assert len(rows) == 2

    def test_new_columns_are_added_on_later_syncs(self, db):
        upsert_records(db, "items", [{"id": "1", "name": "first"}])
        upsert_records(db, "items", [{"id": "2", "name": "second", "status": "active"}])
        rows = query_table(db, "items", limit=10)
        assert rows[0]["status"] == "active"
        assert rows[1]["status"] is None

    def test_existing_non_unique_table_is_migrated_to_real_upserts(self, db):
        conn = sqlite3.connect(db)
        conn.execute('CREATE TABLE "legacy_users" (_row_id INTEGER PRIMARY KEY AUTOINCREMENT, "id" TEXT, "name" TEXT)')
        conn.executemany(
            'INSERT INTO "legacy_users" ("id", "name") VALUES (?, ?)',
            [("1", "Alice"), ("1", "Bob")],
        )
        conn.commit()
        conn.close()

        upsert_records(db, "legacy_users", [{"id": "1", "name": "Carol"}])
        rows = query_table(db, "legacy_users", limit=10)
        assert len(rows) == 1
        assert rows[0]["name"] == "Carol"

    def test_query_nonexistent_table_returns_empty(self, db):
        rows = query_table(db, "nonexistent")
        assert rows == []

    def test_query_operational_failure_is_surfaced(self, db):
        class BrokenConnection:
            def execute(self, *_args, **_kwargs):
                raise sqlite3.OperationalError("database is locked")

            def close(self):
                return None

        with patch("api_sync.storage._connect", return_value=BrokenConnection()):
            with pytest.raises(StorageError, match="database is locked"):
                query_table(db, "users")


class TestCursorManagement:
    def test_load_cursor_none_before_any_sync(self, db):
        assert load_cursor(db, "mysource") is None

    def test_save_and_load_cursor(self, db):
        save_cursor(db, "mysource", "2024-06-01T00:00:00", upserted=5)
        assert load_cursor(db, "mysource") == "2024-06-01T00:00:00"

    def test_cursor_updates_on_second_save(self, db):
        save_cursor(db, "src", "v1", upserted=3)
        save_cursor(db, "src", "v2", upserted=7)
        assert load_cursor(db, "src") == "v2"

    def test_null_cursor_saved_as_none(self, db):
        save_cursor(db, "src", None, upserted=0)
        assert load_cursor(db, "src") is None


class TestSyncStatus:
    def test_empty_before_any_run(self, db):
        rows = get_sync_status(db)
        assert rows == []

    def test_shows_run_after_save(self, db):
        save_cursor(db, "api_a", "tok1", upserted=10)
        rows = get_sync_status(db)
        assert len(rows) == 1
        assert rows[0]["source"] == "api_a"
        assert rows[0]["total_upserted"] == 10

    def test_total_upserted_accumulates(self, db):
        save_cursor(db, "api_a", "tok1", upserted=10)
        save_cursor(db, "api_a", "tok2", upserted=5)
        rows = get_sync_status(db)
        assert rows[0]["total_upserted"] == 15

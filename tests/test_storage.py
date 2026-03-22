"""Tests for the SQLite storage layer."""

import json
import tempfile
import os

import pytest

from api_sync.storage import (
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
        names = [r["name"] for r in rows]
        assert "Bob" in names

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

    def test_query_nonexistent_table_returns_empty(self, db):
        rows = query_table(db, "nonexistent")
        assert rows == []


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

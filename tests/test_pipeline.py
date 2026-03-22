"""Integration tests for run_sync."""

import tempfile
import os
from unittest.mock import patch

import pytest

from api_sync.fetcher import FetchError
from api_sync.models import SyncConfig, SyncRecord
from api_sync.pipeline import run_sync
from api_sync.storage import load_cursor, query_table


BASE = SyncConfig(
    name="api_a",
    base_url="https://api.example.com",
    endpoint="/records",
    table="records",
    id_field="id",
    page_size=10,
)


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    os.unlink(path)


def _make_records(*ids) -> list[tuple[SyncRecord, str | None]]:
    return [
        (SyncRecord(source="api_a", table="records", record_id=str(i), payload={"id": str(i), "val": i}), None)
        for i in ids
    ]


class TestRunSync:
    def test_fetched_and_upserted_counts(self, db):
        with patch("api_sync.pipeline.fetch_records", return_value=_make_records(1, 2, 3)):
            result = run_sync(BASE, db)
        assert result.fetched == 3
        assert result.upserted == 3
        assert result.success

    def test_records_persisted_to_db(self, db):
        with patch("api_sync.pipeline.fetch_records", return_value=_make_records(10, 20)):
            run_sync(BASE, db)
        rows = query_table(db, "records")
        ids = {r["id"] for r in rows}
        assert "10" in ids
        assert "20" in ids

    def test_cursor_saved_after_sync(self, db):
        records = [
            (SyncRecord("api_a", "records", "1", {"id": "1"}), "cursor_v1"),
            (SyncRecord("api_a", "records", "2", {"id": "2"}), "cursor_v2"),
        ]
        with patch("api_sync.pipeline.fetch_records", return_value=records):
            run_sync(BASE, db)
        assert load_cursor(db, "api_a") == "cursor_v2"

    def test_full_refresh_ignores_cursor(self, db):
        with patch("api_sync.pipeline.fetch_records", return_value=_make_records(1)) as mock_fetch:
            run_sync(BASE, db)
            run_sync(BASE, db, full_refresh=True)
        # Second call should pass since_cursor=None
        second_call_kwargs = mock_fetch.call_args_list[1][1]
        assert second_call_kwargs.get("since_cursor") is None

    def test_fetch_error_returns_failed_result(self, db):
        with patch("api_sync.pipeline.fetch_records", side_effect=FetchError("timeout")):
            result = run_sync(BASE, db)
        assert not result.success
        assert "timeout" in result.error_message

    def test_transform_error_increments_errors(self, db):
        def bad_transform(record):
            raise ValueError("bad")

        with patch("api_sync.pipeline.fetch_records", return_value=_make_records(1, 2)):
            result = run_sync(BASE, db, transform=bad_transform)
        assert result.errors == 2
        assert result.upserted == 0

    def test_incremental_sync_uses_saved_cursor(self, db):
        records_p1 = [(SyncRecord("api_a", "records", "1", {"id": "1"}), "tok1")]
        records_p2 = [(SyncRecord("api_a", "records", "2", {"id": "2"}), None)]

        with patch("api_sync.pipeline.fetch_records", return_value=records_p1) as mock_fetch:
            run_sync(BASE, db)

        with patch("api_sync.pipeline.fetch_records", return_value=records_p2) as mock_fetch2:
            run_sync(BASE, db)

        # Second run should pass the saved cursor as since_cursor
        call_kwargs = mock_fetch2.call_args[1]
        assert call_kwargs.get("since_cursor") == "tok1"

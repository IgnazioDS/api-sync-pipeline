"""Tests for the HTTP fetcher."""

import pytest
import responses as resp_lib
import requests

from api_sync.fetcher import FetchError, fetch_records, _extract_records, _extract_next_cursor
from api_sync.models import SyncConfig


BASE_CONFIG = SyncConfig(
    name="test",
    base_url="https://api.example.com",
    endpoint="/items",
    table="items",
    id_field="id",
    cursor_field="updated_at",
    page_size=2,
)


class TestExtractRecords:
    def test_list_response(self):
        assert _extract_records([{"id": 1}], "id") == [{"id": 1}]

    def test_data_envelope(self):
        assert _extract_records({"data": [{"id": 2}]}, "id") == [{"id": 2}]

    def test_results_envelope(self):
        assert _extract_records({"results": [{"id": 3}]}, "id") == [{"id": 3}]

    def test_items_envelope(self):
        assert _extract_records({"items": [{"id": 4}]}, "id") == [{"id": 4}]

    def test_empty_dict_returns_empty(self):
        assert _extract_records({"other": "stuff"}, "id") == []


class TestExtractNextCursor:
    def test_top_level_next_cursor(self):
        assert _extract_next_cursor({"next_cursor": "abc"}) == "abc"

    def test_nested_meta_cursor(self):
        assert _extract_next_cursor({"meta": {"next_cursor": "xyz"}}) == "xyz"

    def test_none_when_absent(self):
        assert _extract_next_cursor({"data": []}) is None

    def test_list_response_returns_none(self):
        assert _extract_next_cursor([1, 2, 3]) is None


@resp_lib.activate
class TestFetchRecords:
    def test_single_page_list_response(self):
        resp_lib.add(
            resp_lib.GET,
            "https://api.example.com/items",
            json=[{"id": 1, "name": "a"}, {"id": 2, "name": "b"}],
            status=200,
        )
        results = list(fetch_records(BASE_CONFIG))
        assert len(results) == 2
        assert results[0][0].record_id == "1"
        assert results[1][0].record_id == "2"

    def test_cursor_pagination(self):
        resp_lib.add(
            resp_lib.GET,
            "https://api.example.com/items",
            json={"data": [{"id": 1}], "next_cursor": "tok1"},
            status=200,
        )
        resp_lib.add(
            resp_lib.GET,
            "https://api.example.com/items",
            json={"data": [{"id": 2}]},
            status=200,
        )
        results = list(fetch_records(BASE_CONFIG))
        assert len(results) == 2
        assert results[0][1] == "tok1"   # first record carries cursor from page 1
        assert results[1][1] is None     # last page has no next cursor

    def test_empty_response_stops_immediately(self):
        resp_lib.add(
            resp_lib.GET,
            "https://api.example.com/items",
            json=[],
            status=200,
        )
        results = list(fetch_records(BASE_CONFIG))
        assert results == []

    def test_http_error_raises_fetch_error(self):
        resp_lib.add(
            resp_lib.GET,
            "https://api.example.com/items",
            status=500,
        )
        with pytest.raises(FetchError):
            list(fetch_records(BASE_CONFIG))

    def test_since_cursor_injected_in_params(self):
        resp_lib.add(
            resp_lib.GET,
            "https://api.example.com/items",
            json=[{"id": 99}],
            status=200,
        )
        results = list(fetch_records(BASE_CONFIG, since_cursor="2024-01-01"))
        assert len(results) == 1
        call_params = resp_lib.calls[0].request.url
        assert "since=2024-01-01" in call_params or "updated_at_gte=2024-01-01" in call_params

    def test_source_set_from_config(self):
        resp_lib.add(
            resp_lib.GET,
            "https://api.example.com/items",
            json=[{"id": 7}],
            status=200,
        )
        results = list(fetch_records(BASE_CONFIG))
        assert results[0][0].source == "test"

    def test_nested_payload_preserved(self):
        resp_lib.add(
            resp_lib.GET,
            "https://api.example.com/items",
            json=[{"id": 1, "meta": {"tags": ["a", "b"]}}],
            status=200,
        )
        results = list(fetch_records(BASE_CONFIG))
        assert results[0][0].payload["meta"] == {"tags": ["a", "b"]}

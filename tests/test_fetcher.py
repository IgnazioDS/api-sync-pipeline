"""Tests for the HTTP fetcher."""

import pytest
import responses as resp_lib

from api_sync.fetcher import FetchError, _extract_next_cursor, _extract_records, fetch_records
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


class TestExtractHelpers:
    def test_extract_records_uses_default_envelopes(self):
        assert _extract_records({"data": [{"id": 1}]}, BASE_CONFIG) == [{"id": 1}]

    def test_extract_records_uses_explicit_records_path(self):
        config = SyncConfig(
            name="test",
            base_url="https://api.example.com",
            endpoint="/items",
            table="items",
            id_field="id",
            records_path="payload.rows",
        )
        assert _extract_records({"payload": {"rows": [{"id": 1}]}}, config) == [{"id": 1}]

    def test_extract_records_rejects_non_list_records_path(self):
        config = SyncConfig(
            name="test",
            base_url="https://api.example.com",
            endpoint="/items",
            table="items",
            records_path="payload.rows",
        )
        with pytest.raises(FetchError, match="records_path"):
            _extract_records({"payload": {"rows": {"id": 1}}}, config)

    def test_extract_next_cursor_uses_explicit_path(self):
        config = SyncConfig(
            name="test",
            base_url="https://api.example.com",
            endpoint="/items",
            table="items",
            next_cursor_path="meta.next",
        )
        assert _extract_next_cursor({"meta": {"next": "tok1"}}, config) == "tok1"


@resp_lib.activate
class TestFetchRecords:
    def test_auto_mode_preserves_default_pagination_heuristics(self):
        resp_lib.add(
            resp_lib.GET,
            "https://api.example.com/items",
            json=[{"id": 1, "name": "a"}, {"id": 2, "name": "b"}],
            status=200,
        )

        results = list(fetch_records(BASE_CONFIG))

        assert len(results) == 2
        request_url = resp_lib.calls[0].request.url
        assert "per_page=2" in request_url
        assert "limit=2" in request_url
        assert "page=1" in request_url

    def test_explicit_offset_mode_sends_only_configured_params(self):
        config = SyncConfig(
            name="orders",
            base_url="https://api.example.com",
            endpoint="/orders",
            table="orders",
            id_field="id",
            page_size=50,
            pagination_mode="offset",
            page_param="page_number",
            page_size_param="page_size",
            since_param="updated_at",
            since_value_mode="gte_suffix",
            request_params={"status": "active"},
        )
        resp_lib.add(
            resp_lib.GET,
            "https://api.example.com/orders",
            json={"items": [{"id": 1}]},
            status=200,
        )

        results = list(fetch_records(config, since_cursor="2024-01-01T00:00:00Z"))

        assert len(results) == 1
        request_url = resp_lib.calls[0].request.url
        assert "page_number=1" in request_url
        assert "page_size=50" in request_url
        assert "updated_at_gte=2024-01-01T00%3A00%3A00Z" in request_url
        assert "status=active" in request_url
        assert "per_page=" not in request_url
        assert "limit=" not in request_url
        assert "since=" not in request_url

    def test_explicit_cursor_mode_uses_cursor_param_on_followup_requests(self):
        config = SyncConfig(
            name="orders",
            base_url="https://api.example.com",
            endpoint="/orders",
            table="orders",
            id_field="id",
            pagination_mode="cursor",
            page_size_param="page_size",
            cursor_param="page_token",
            next_cursor_path="meta.next_cursor",
            records_path="payload.rows",
        )
        resp_lib.add(
            resp_lib.GET,
            "https://api.example.com/orders",
            json={"payload": {"rows": [{"id": 1}]}, "meta": {"next_cursor": "tok1"}},
            status=200,
        )
        resp_lib.add(
            resp_lib.GET,
            "https://api.example.com/orders",
            json={"payload": {"rows": [{"id": 2}]}, "meta": {"next_cursor": None}},
            status=200,
        )

        results = list(fetch_records(config))

        assert len(results) == 2
        assert "page_token=" not in resp_lib.calls[0].request.url
        assert "page_token=tok1" in resp_lib.calls[1].request.url
        assert "page=1" not in resp_lib.calls[0].request.url

    def test_explicit_mode_does_not_send_since_when_since_param_unset(self):
        config = SyncConfig(
            name="orders",
            base_url="https://api.example.com",
            endpoint="/orders",
            table="orders",
            pagination_mode="none",
        )
        resp_lib.add(
            resp_lib.GET,
            "https://api.example.com/orders",
            json=[{"id": 1}],
            status=200,
        )

        list(fetch_records(config, since_cursor="tok1"))

        request_url = resp_lib.calls[0].request.url
        assert "since=" not in request_url
        assert "_gte=" not in request_url

    def test_invalid_json_raises_fetch_error(self):
        resp_lib.add(
            resp_lib.GET,
            "https://api.example.com/items",
            body="not-json",
            status=200,
            content_type="text/plain",
        )

        with pytest.raises(FetchError, match="valid JSON"):
            list(fetch_records(BASE_CONFIG))

"""HTTP fetcher with configurable pagination and incremental sync behavior."""

import logging
import time
from typing import Any, Iterator

import requests
from requests import Response

from api_sync.models import SyncConfig, SyncRecord

logger = logging.getLogger(__name__)

_RETRY_DELAYS = [1, 2, 4]  # seconds


class FetchError(Exception):
    """Raised when fetching or decoding records fails."""


def _get_with_retry(url: str, params: dict[str, Any], headers: dict[str, str], timeout: int) -> Response:
    last_exc: Exception | None = None
    for attempt, delay in enumerate([0] + _RETRY_DELAYS, start=1):
        if delay:
            time.sleep(delay)
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            logger.warning("Attempt %d failed for %s: %s", attempt, url, exc)
            last_exc = exc
    raise FetchError(f"All retries exhausted for {url}") from last_exc


def _get_path_value(data: Any, path: str | None) -> Any:
    if not path:
        return data
    current = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _extract_records(data: Any, config: SyncConfig) -> list[dict]:
    """Pull the record list out of whatever envelope the API uses."""
    if config.records_path:
        value = _get_path_value(data, config.records_path)
        if value is None:
            return []
        if not isinstance(value, list):
            raise FetchError(f"records_path '{config.records_path}' did not resolve to a list")
        return value

    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in ("data", "results", "items", "records"):
        if key in data and isinstance(data[key], list):
            return data[key]
    return []


def _extract_next_cursor(data: Any, config: SyncConfig) -> str | None:
    if config.next_cursor_path:
        value = _get_path_value(data, config.next_cursor_path)
        return str(value) if value not in (None, "") else None
    if not isinstance(data, dict):
        return None
    for key in ("next_cursor", "cursor", "next_page_token", "next"):
        val = data.get(key)
        if val:
            return str(val)
    meta = data.get("meta") or data.get("pagination") or {}
    for key in ("next_cursor", "cursor"):
        val = meta.get(key)
        if val:
            return str(val)
    return None


def _build_since_params(config: SyncConfig, since_cursor: str | None) -> dict[str, Any]:
    if not since_cursor:
        return {}
    if config.pagination_mode == "auto":
        return {
            f"{config.cursor_field}_gte": since_cursor,
            "since": since_cursor,
        }
    if not config.since_param:
        return {}
    if config.since_value_mode == "gte_suffix":
        return {f"{config.since_param}_gte": since_cursor}
    return {config.since_param: since_cursor}


def _build_base_params(config: SyncConfig, since_cursor: str | None) -> dict[str, Any]:
    params = dict(config.request_params)
    params.update(_build_since_params(config, since_cursor))

    if config.pagination_mode == "auto":
        params["per_page"] = config.page_size
        params["limit"] = config.page_size
    elif config.page_size_param:
        params[config.page_size_param] = config.page_size
    return params


def fetch_records(
    config: SyncConfig,
    since_cursor: str | None = None,
) -> Iterator[tuple[SyncRecord, str | None]]:
    """
    Yield (SyncRecord, cursor) pairs.
    Supports auto, offset, cursor, and single-request modes.
    """
    url = config.base_url.rstrip("/") + "/" + config.endpoint.lstrip("/")
    base_params = _build_base_params(config, since_cursor)
    cursor: str | None = None
    page = 1

    while True:
        params = dict(base_params)
        if config.pagination_mode == "offset":
            params[config.page_param] = page
        elif config.pagination_mode == "cursor" and cursor:
            params[config.cursor_param] = cursor
        elif config.pagination_mode == "auto":
            params["page"] = page
            if cursor:
                params[config.cursor_param] = cursor
                params.pop("page", None)

        logger.debug("GET %s params=%s", url, params)
        resp = _get_with_retry(url, params, config.request_headers, config.timeout)
        try:
            data = resp.json()
        except ValueError as exc:
            raise FetchError(f"Response from {url} was not valid JSON") from exc

        records = _extract_records(data, config)
        if not records:
            break

        next_cursor = _extract_next_cursor(data, config)
        for raw in records:
            record_id = str(raw.get(config.id_field, ""))
            yield SyncRecord(
                source=config.name,
                table=config.table,
                record_id=record_id,
                payload=raw,
            ), next_cursor

        if config.pagination_mode == "none":
            break

        if config.pagination_mode == "cursor":
            if not next_cursor:
                break
            cursor = next_cursor
        elif config.pagination_mode == "offset":
            page += 1
            if len(records) < config.page_size:
                break
        else:
            if next_cursor:
                cursor = next_cursor
            else:
                page += 1
                if len(records) < config.page_size:
                    break

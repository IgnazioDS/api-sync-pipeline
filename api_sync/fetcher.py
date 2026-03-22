"""HTTP fetcher with pagination, retry, and cursor-based incremental sync."""

import logging
import time
from typing import Iterator

import requests
from requests import Response

from api_sync.models import SyncConfig, SyncRecord

logger = logging.getLogger(__name__)

_RETRY_DELAYS = [1, 2, 4]  # seconds


class FetchError(Exception):
    pass


def _get_with_retry(url: str, params: dict, headers: dict, timeout: int) -> Response:
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


def _extract_records(data: Any, id_field: str) -> list[dict]:
    """Pull the record list out of whatever envelope the API uses."""
    if isinstance(data, list):
        return data
    for key in ("data", "results", "items", "records"):
        if key in data and isinstance(data[key], list):
            return data[key]
    return []


def _extract_next_cursor(data: Any) -> str | None:
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


def fetch_records(
    config: SyncConfig,
    since_cursor: str | None = None,
) -> Iterator[tuple[SyncRecord, str | None]]:
    """
    Yield (SyncRecord, cursor) pairs.
    Handles offset-based and cursor-based pagination transparently.
    Stops when the API returns an empty page or no next_cursor.
    """
    url = config.base_url.rstrip("/") + "/" + config.endpoint.lstrip("/")
    page_params: dict = {**config.params, "per_page": config.page_size, "limit": config.page_size}

    if since_cursor:
        page_params[config.cursor_field + "_gte"] = since_cursor
        page_params["since"] = since_cursor

    cursor: str | None = None
    page = 1

    while True:
        params = {**page_params, "page": page}
        if cursor:
            params["cursor"] = cursor
            params.pop("page", None)

        logger.debug("GET %s params=%s", url, params)
        resp = _get_with_retry(url, params, config.headers, config.timeout)
        data = resp.json()

        records = _extract_records(data, config.id_field)
        if not records:
            break

        next_cursor = _extract_next_cursor(data)

        for raw in records:
            record_id = str(raw.get(config.id_field, ""))
            yield SyncRecord(
                source=config.name,
                table=config.table,
                record_id=record_id,
                payload=raw,
            ), next_cursor

        if not next_cursor:
            page += 1
            # Stop after offset pagination if we got a short page
            if len(records) < config.page_size:
                break
        else:
            cursor = next_cursor
            page_params.pop("page", None)


# Avoid the `Any` import issue at runtime by importing at module level
from typing import Any  # noqa: E402  (already imported above, re-alias for _extract_records signature)

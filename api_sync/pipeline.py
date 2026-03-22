"""Orchestrates fetch → transform → store for one SyncConfig."""

import logging
from typing import Callable

from api_sync.fetcher import FetchError, fetch_records
from api_sync.models import SyncConfig, SyncRecord, SyncResult
from api_sync.storage import load_cursor, save_cursor, upsert_records

logger = logging.getLogger(__name__)

TransformFn = Callable[[SyncRecord], dict]


def _default_transform(record: SyncRecord) -> dict:
    return dict(record.payload)


def run_sync(
    config: SyncConfig,
    db_path: str,
    transform: TransformFn = _default_transform,
    full_refresh: bool = False,
) -> SyncResult:
    """
    Run one sync cycle for `config`:
    1. Load the last cursor from DB (skip if full_refresh)
    2. Page through the API
    3. Upsert each batch of records
    4. Persist the new cursor
    """
    since = None if full_refresh else load_cursor(db_path, config.name)
    logger.info("Starting sync '%s' since=%s full_refresh=%s", config.name, since, full_refresh)

    batch: list[dict] = []
    fetched = 0
    upserted = 0
    errors = 0
    last_cursor: str | None = since
    batch_size = 50

    try:
        for record, cursor in fetch_records(config, since_cursor=since):
            try:
                transformed = transform(record)
                batch.append(transformed)
                if cursor:
                    last_cursor = cursor
            except Exception as exc:
                logger.warning("Transform error for record %s: %s", record.record_id, exc)
                errors += 1
                continue

            fetched += 1

            if len(batch) >= batch_size:
                upserted += upsert_records(db_path, config.table, batch)
                batch = []

        if batch:
            upserted += upsert_records(db_path, config.table, batch)

    except FetchError as exc:
        logger.error("Fetch failed for '%s': %s", config.name, exc)
        return SyncResult(
            source=config.name,
            fetched=fetched,
            upserted=upserted,
            errors=errors,
            cursor=last_cursor,
            error_message=str(exc),
        )

    save_cursor(db_path, config.name, last_cursor, upserted)
    logger.info(
        "Sync '%s' complete: fetched=%d upserted=%d errors=%d cursor=%s",
        config.name, fetched, upserted, errors, last_cursor,
    )
    return SyncResult(
        source=config.name,
        fetched=fetched,
        upserted=upserted,
        errors=errors,
        cursor=last_cursor,
    )

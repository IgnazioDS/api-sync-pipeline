"""Immutable data models for the sync pipeline."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SyncConfig:
    name: str
    base_url: str
    endpoint: str
    table: str
    id_field: str = "id"
    cursor_field: str = "updated_at"
    page_size: int = 100
    headers: dict[str, str] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    timeout: int = 30


@dataclass(frozen=True)
class SyncRecord:
    source: str
    table: str
    record_id: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class SyncResult:
    source: str
    fetched: int
    upserted: int
    errors: int
    cursor: str | None = None
    error_message: str | None = None

    @property
    def success(self) -> bool:
        return self.error_message is None

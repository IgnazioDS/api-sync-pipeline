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
    request_headers: dict[str, str] = field(default_factory=dict)
    request_params: dict[str, Any] = field(default_factory=dict)
    pagination_mode: str = "auto"
    records_path: str | None = None
    next_cursor_path: str | None = None
    page_param: str = "page"
    page_size_param: str | None = None
    cursor_param: str = "cursor"
    since_param: str | None = None
    since_value_mode: str = "raw"
    timeout: int = 30

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("SyncConfig.name must not be empty")
        if not self.base_url.strip():
            raise ValueError("SyncConfig.base_url must not be empty")
        if not self.endpoint.strip():
            raise ValueError("SyncConfig.endpoint must not be empty")
        if not self.table.strip():
            raise ValueError("SyncConfig.table must not be empty")
        if not self.id_field.strip():
            raise ValueError("SyncConfig.id_field must not be empty")
        if not self.cursor_field.strip():
            raise ValueError("SyncConfig.cursor_field must not be empty")
        if self.page_size <= 0:
            raise ValueError("SyncConfig.page_size must be greater than zero")
        if self.timeout <= 0:
            raise ValueError("SyncConfig.timeout must be greater than zero")
        if self.pagination_mode not in {"auto", "offset", "cursor", "none"}:
            raise ValueError("SyncConfig.pagination_mode must be one of: auto, offset, cursor, none")
        if self.since_value_mode not in {"raw", "gte_suffix"}:
            raise ValueError("SyncConfig.since_value_mode must be one of: raw, gte_suffix")
        if not self.page_param.strip():
            raise ValueError("SyncConfig.page_param must not be empty")
        if self.page_size_param is not None and not self.page_size_param.strip():
            raise ValueError("SyncConfig.page_size_param must not be empty when provided")
        if not self.cursor_param.strip():
            raise ValueError("SyncConfig.cursor_param must not be empty")
        if self.since_param is not None and not self.since_param.strip():
            raise ValueError("SyncConfig.since_param must not be empty when provided")
        if self.records_path is not None and not self.records_path.strip():
            raise ValueError("SyncConfig.records_path must not be empty when provided")
        if self.next_cursor_path is not None and not self.next_cursor_path.strip():
            raise ValueError("SyncConfig.next_cursor_path must not be empty when provided")

        effective_headers = self.request_headers or self.headers
        effective_params = self.request_params or self.params
        object.__setattr__(self, "headers", dict(effective_headers))
        object.__setattr__(self, "params", dict(effective_params))
        object.__setattr__(self, "request_headers", dict(effective_headers))
        object.__setattr__(self, "request_params", dict(effective_params))


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

"""Config loading helpers for YAML-driven sync jobs."""

import os
import re
from pathlib import Path
from typing import Any

import yaml

from api_sync.models import SyncConfig

_UNRESOLVED_ENV_PATTERN = re.compile(r"\$\{[^}]+\}")
_STRING_FIELDS = {
    "name",
    "base_url",
    "endpoint",
    "table",
    "id_field",
    "cursor_field",
    "pagination_mode",
    "records_path",
    "next_cursor_path",
    "page_param",
    "page_size_param",
    "cursor_param",
    "since_param",
    "since_value_mode",
}
_MAPPING_FIELDS = {"headers", "params", "request_headers", "request_params"}
_INT_FIELDS = {"page_size", "timeout"}
_ALLOWED_PAGINATION_MODES = {"auto", "offset", "cursor", "none"}
_ALLOWED_SINCE_VALUE_MODES = {"raw", "gte_suffix"}


class ConfigError(ValueError):
    """Raised when a sync config is invalid."""


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        expanded = os.path.expandvars(value)
        if _UNRESOLVED_ENV_PATTERN.search(expanded):
            raise ConfigError(f"Unresolved environment variable in config value: {value}")
        return expanded
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    return value


def _require_mapping(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ConfigError("Config file must contain a YAML mapping")
    return raw


def _require_string(data: dict[str, Any], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"Config field '{field}' must be a non-empty string")
    return value


def _validate_optional_string_fields(data: dict[str, Any]) -> None:
    for field in _STRING_FIELDS - {"name", "base_url", "endpoint", "table"}:
        if field not in data or data[field] is None:
            continue
        if not isinstance(data[field], str) or not data[field].strip():
            raise ConfigError(f"Config field '{field}' must be a non-empty string when provided")


def _validate_mapping_fields(data: dict[str, Any]) -> None:
    for field in _MAPPING_FIELDS:
        if field not in data:
            continue
        if not isinstance(data[field], dict):
            raise ConfigError(f"Config field '{field}' must be a mapping")


def _validate_int_fields(data: dict[str, Any]) -> None:
    for field in _INT_FIELDS:
        if field not in data:
            continue
        if not isinstance(data[field], int) or isinstance(data[field], bool) or data[field] <= 0:
            raise ConfigError(f"Config field '{field}' must be a positive integer")


def _validate_choice_fields(data: dict[str, Any]) -> None:
    pagination_mode = data.get("pagination_mode", "auto")
    if pagination_mode not in _ALLOWED_PAGINATION_MODES:
        raise ConfigError("Config field 'pagination_mode' must be one of: auto, offset, cursor, none")

    since_value_mode = data.get("since_value_mode", "raw")
    if since_value_mode not in _ALLOWED_SINCE_VALUE_MODES:
        raise ConfigError("Config field 'since_value_mode' must be one of: raw, gte_suffix")


def _validate_compatibility(data: dict[str, Any]) -> None:
    records_path = data.get("records_path")
    next_cursor_path = data.get("next_cursor_path")
    pagination_mode = data.get("pagination_mode", "auto")

    if pagination_mode == "none" and next_cursor_path:
        raise ConfigError("Config field 'next_cursor_path' cannot be used when pagination_mode is 'none'")
    if pagination_mode == "offset" and next_cursor_path:
        raise ConfigError("Config field 'next_cursor_path' cannot be used when pagination_mode is 'offset'")
    if pagination_mode == "none" and data.get("page_param", "page") != "page":
        raise ConfigError("Config field 'page_param' cannot be customized when pagination_mode is 'none'")
    if records_path is not None and ".." in records_path:
        raise ConfigError("Config field 'records_path' must be a dot path without empty segments")
    if next_cursor_path is not None and ".." in next_cursor_path:
        raise ConfigError("Config field 'next_cursor_path' must be a dot path without empty segments")


def _normalize_config(data: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(data)
    normalized.setdefault("id_field", "id")
    normalized.setdefault("cursor_field", "updated_at")
    normalized.setdefault("page_size", 100)
    normalized.setdefault("timeout", 30)
    normalized.setdefault("pagination_mode", "auto")
    normalized.setdefault("page_param", "page")
    normalized.setdefault("cursor_param", "cursor")
    normalized.setdefault("since_value_mode", "raw")
    normalized.setdefault("headers", {})
    normalized.setdefault("params", {})
    normalized.setdefault("request_headers", normalized.get("headers", {}))
    normalized.setdefault("request_params", normalized.get("params", {}))
    return normalized


def load_config(path: str | Path) -> SyncConfig:
    with open(path, encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    data = _normalize_config(_expand_env(_require_mapping(raw)))
    for field in ("name", "base_url", "endpoint", "table"):
        _require_string(data, field)
    _validate_optional_string_fields(data)
    _validate_mapping_fields(data)
    _validate_int_fields(data)
    _validate_choice_fields(data)
    _validate_compatibility(data)

    try:
        return SyncConfig(
            name=data["name"],
            base_url=data["base_url"],
            endpoint=data["endpoint"],
            table=data["table"],
            id_field=data["id_field"],
            cursor_field=data["cursor_field"],
            page_size=data["page_size"],
            headers=data["headers"],
            params=data["params"],
            request_headers=data["request_headers"],
            request_params=data["request_params"],
            pagination_mode=data["pagination_mode"],
            records_path=data.get("records_path"),
            next_cursor_path=data.get("next_cursor_path"),
            page_param=data["page_param"],
            page_size_param=data.get("page_size_param"),
            cursor_param=data["cursor_param"],
            since_param=data.get("since_param"),
            since_value_mode=data["since_value_mode"],
            timeout=data["timeout"],
        )
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc

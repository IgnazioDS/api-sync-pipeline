"""Tests for YAML config loading and validation."""

import textwrap

import pytest

from api_sync.config import ConfigError, load_config


def test_load_config_expands_environment_variables(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            name: secured_source
            base_url: https://api.example.com
            endpoint: /v1/orders
            table: orders
            request_headers:
              Authorization: Bearer ${API_TOKEN}
            request_params:
              region: ${SYNC_REGION}
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("API_TOKEN", "secret-token")
    monkeypatch.setenv("SYNC_REGION", "apac")

    config = load_config(config_path)

    assert config.request_headers["Authorization"] == "Bearer secret-token"
    assert config.request_params["region"] == "apac"


def test_load_config_rejects_missing_required_fields(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            name: secured_source
            base_url: https://api.example.com
            table: orders
            """
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="endpoint"):
        load_config(config_path)


def test_load_config_rejects_invalid_choice_values(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            name: secured_source
            base_url: https://api.example.com
            endpoint: /v1/orders
            table: orders
            pagination_mode: strange
            """
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="pagination_mode"):
        load_config(config_path)


def test_load_config_rejects_invalid_mapping_types(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            name: secured_source
            base_url: https://api.example.com
            endpoint: /v1/orders
            table: orders
            request_headers: nope
            """
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="request_headers"):
        load_config(config_path)


def test_load_config_rejects_unresolved_environment_variables(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            name: secured_source
            base_url: https://api.example.com
            endpoint: /v1/orders
            table: orders
            request_headers:
              Authorization: Bearer ${MISSING_TOKEN}
            """
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="Unresolved environment variable"):
        load_config(config_path)


def test_load_config_requires_mapping(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("- not-a-mapping\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="YAML mapping"):
        load_config(config_path)

"""Tests for CLI behavior."""

import textwrap

from api_sync.storage import upsert_records
from main import main, parse_args


def test_parse_args_accepts_db_after_subcommand():
    args = parse_args(["status", "--db", "customer-demo.db"])
    assert args.cmd == "status"
    assert args.db == "customer-demo.db"


def test_parse_args_accepts_db_before_subcommand():
    args = parse_args(["--db", "customer-demo.db", "status"])
    assert args.cmd == "status"
    assert args.db == "customer-demo.db"


def test_validate_config_command_returns_zero_for_valid_config(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            name: demo_source
            base_url: https://api.example.com
            endpoint: /v1/orders
            table: orders
            pagination_mode: none
            """
        ),
        encoding="utf-8",
    )

    exit_code = main(["validate-config", "--config", str(config_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Config valid:" in captured.out


def test_validate_config_command_returns_error_for_invalid_config(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            name: demo_source
            base_url: https://api.example.com
            table: orders
            """
        ),
        encoding="utf-8",
    )

    exit_code = main(["validate-config", "--config", str(config_path)])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Config error:" in captured.err


def test_query_supports_table_output(tmp_path, capsys):
    db_path = tmp_path / "sync.db"
    upsert_records(str(db_path), "orders", [{"id": "1", "name": "Alice"}])

    exit_code = main(["query", "--db", str(db_path), "--table", "orders", "--format", "table"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "name" in captured.out
    assert "Alice" in captured.out


def test_query_supports_json_output(tmp_path, capsys):
    db_path = tmp_path / "sync.db"
    upsert_records(str(db_path), "orders", [{"id": "1", "name": "Alice"}])

    exit_code = main(["query", "--db", str(db_path), "--table", "orders", "--format", "json"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert '"name": "Alice"' in captured.out

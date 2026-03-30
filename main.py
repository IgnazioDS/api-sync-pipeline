"""CLI for api-sync-pipeline."""

import argparse
import json
import logging
import sys

from api_sync.config import ConfigError, load_config
from api_sync.pipeline import run_sync
from api_sync.storage import StorageError, get_sync_status, query_table

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


def _format_table(rows: list[dict]) -> str:
    if not rows:
        return ""

    columns: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in columns:
                columns.append(key)

    widths = {
        column: max(len(str(column)), max(len(str(row.get(column, ""))) for row in rows))
        for column in columns
    }

    header = " | ".join(f"{column:<{widths[column]}}" for column in columns)
    divider = "-+-".join("-" * widths[column] for column in columns)
    body = [
        " | ".join(f"{str(row.get(column, '')):<{widths[column]}}" for column in columns)
        for row in rows
    ]
    return "\n".join([header, divider, *body])


def cmd_validate_config(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    print(
        f"Config valid: source={config.name} table={config.table} "
        f"pagination_mode={config.pagination_mode}"
    )
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = run_sync(config, args.db, full_refresh=args.full_refresh)
    if not result.success:
        print(f"Sync failed: {result.error_message}", file=sys.stderr)
        return 1

    print(json.dumps({
        "source": result.source,
        "fetched": result.fetched,
        "upserted": result.upserted,
        "errors": result.errors,
        "cursor": result.cursor,
        "success": result.success,
    }, indent=2))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    rows = get_sync_status(args.db)
    if not rows:
        print("No sync runs recorded.")
        return 0
    print(f"{'Source':<25} {'Last run':<22} {'Cursor':<25} {'Total upserted'}")
    print("-" * 85)
    for row in rows:
        print(
            f"{row['source']:<25} {row['last_run_at']:<22} "
            f"{str(row['last_cursor'] or 'none'):<25} {row['total_upserted']}"
        )
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    rows = query_table(args.db, args.table, limit=args.limit)
    if not rows:
        print(f"Table '{args.table}' is empty or does not exist.")
        return 0
    if args.format == "table":
        print(_format_table(rows))
    else:
        print(json.dumps(rows, indent=2, default=str))
    return 0


def build_parser(default_db: str = "sync.db") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Configurable REST API to SQLite sync pipeline")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_validate = sub.add_parser("validate-config", help="Validate a YAML sync config file")
    p_validate.add_argument("--config", required=True, help="Path to YAML sync config")

    p_sync = sub.add_parser("sync", help="Run a sync from a YAML config file")
    p_sync.add_argument("--db", default=default_db, help="SQLite database path")
    p_sync.add_argument("--config", required=True, help="Path to YAML sync config")
    p_sync.add_argument("--full-refresh", action="store_true", help="Ignore cursor, re-fetch all records")

    p_status = sub.add_parser("status", help="Show sync run history")
    p_status.add_argument("--db", default=default_db, help="SQLite database path")

    p_query = sub.add_parser("query", help="Preview rows in a synced table")
    p_query.add_argument("--db", default=default_db, help="SQLite database path")
    p_query.add_argument("--table", required=True)
    p_query.add_argument("--limit", type=int, default=20)
    p_query.add_argument("--format", choices=("json", "table"), default="json")
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    db_parser = argparse.ArgumentParser(add_help=False)
    db_parser.add_argument("--db", default="sync.db")
    defaults, remaining = db_parser.parse_known_args(argv)
    return build_parser(default_db=defaults.db).parse_args(remaining)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        dispatch = {
            "validate-config": cmd_validate_config,
            "sync": cmd_sync,
            "status": cmd_status,
            "query": cmd_query,
        }
        return dispatch[args.cmd](args)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    except StorageError as exc:
        print(f"Storage error: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

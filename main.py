"""CLI for api-sync-pipeline.

Usage:
  python main.py sync --config examples/github_repos.yaml
  python main.py sync --config examples/github_repos.yaml --full-refresh
  python main.py status --db sync.db
  python main.py query --db sync.db --table github_repos --limit 5
"""

import argparse
import json
import logging
import sys
import yaml

from api_sync.models import SyncConfig
from api_sync.pipeline import run_sync
from api_sync.storage import get_sync_status, query_table

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


def _load_config(path: str) -> SyncConfig:
    with open(path) as f:
        data = yaml.safe_load(f)
    return SyncConfig(
        name=data["name"],
        base_url=data["base_url"],
        endpoint=data["endpoint"],
        table=data["table"],
        id_field=data.get("id_field", "id"),
        cursor_field=data.get("cursor_field", "updated_at"),
        page_size=data.get("page_size", 100),
        headers=data.get("headers", {}),
        params=data.get("params", {}),
        timeout=data.get("timeout", 30),
    )


def cmd_sync(args: argparse.Namespace) -> int:
    config = _load_config(args.config)
    result = run_sync(config, args.db, full_refresh=args.full_refresh)
    print(json.dumps({
        "source": result.source,
        "fetched": result.fetched,
        "upserted": result.upserted,
        "errors": result.errors,
        "cursor": result.cursor,
        "success": result.success,
        "error_message": result.error_message,
    }, indent=2))
    return 0 if result.success else 1


def cmd_status(args: argparse.Namespace) -> int:
    rows = get_sync_status(args.db)
    if not rows:
        print("No sync runs recorded.")
        return 0
    print(f"{'Source':<25} {'Last run':<22} {'Cursor':<25} {'Total upserted'}")
    print("-" * 85)
    for r in rows:
        print(f"{r['source']:<25} {r['last_run_at']:<22} {str(r['last_cursor'] or 'none'):<25} {r['total_upserted']}")
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    rows = query_table(args.db, args.table, limit=args.limit)
    if not rows:
        print(f"Table '{args.table}' is empty or does not exist.")
        return 0
    print(json.dumps(rows, indent=2, default=str))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Incremental REST API → SQLite sync pipeline")
    parser.add_argument("--db", default="sync.db", help="SQLite database path")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_sync = sub.add_parser("sync", help="Run a sync from a YAML config file")
    p_sync.add_argument("--config", required=True, help="Path to YAML sync config")
    p_sync.add_argument("--full-refresh", action="store_true", help="Ignore cursor, re-fetch all records")

    p_status = sub.add_parser("status", help="Show sync run history")

    p_query = sub.add_parser("query", help="Preview rows in a synced table")
    p_query.add_argument("--table", required=True)
    p_query.add_argument("--limit", type=int, default=20)

    args = parser.parse_args()
    dispatch = {"sync": cmd_sync, "status": cmd_status, "query": cmd_query}
    sys.exit(dispatch[args.cmd](args))


if __name__ == "__main__":
    main()

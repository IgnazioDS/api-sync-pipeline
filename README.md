# api-sync-pipeline

Incremental REST API → SQLite sync engine. Fetches paginated JSON responses from any REST API, normalises the records, and upserts them to a local SQLite database. Resumes from where it left off via cursor-based incremental sync.

## Features

- **Cursor-based incremental sync** — stores the last cursor per source; subsequent runs only fetch new/updated records
- **Auto-pagination** — handles both offset-based (`page=N`) and cursor-based (`next_cursor`) pagination transparently
- **Dynamic schema** — creates the target table on first run; no migration files required
- **Nested payload support** — nested dicts/lists are serialised to JSON strings automatically
- **Retry with backoff** — transient HTTP errors are retried up to 3 times with exponential backoff
- **Custom transforms** — pass a `transform(SyncRecord) -> dict` function to reshape records before storage
- **YAML config** — one config file per API source; no code changes needed to add a new source

## Project layout

```
api_sync/
  models.py      # Immutable dataclasses: SyncConfig, SyncRecord, SyncResult
  fetcher.py     # HTTP fetch with pagination + retry
  storage.py     # SQLite upsert, cursor persistence, status queries
  pipeline.py    # Orchestrates fetch → transform → store
main.py          # CLI: sync / status / query
examples/
  github_repos.yaml           # Sync public GitHub repos
  jsonplaceholder_posts.yaml  # Test against JSONPlaceholder API
tests/
  test_fetcher.py   # 9 unit tests
  test_storage.py   # 14 unit tests
  test_pipeline.py  # 7 integration tests
```

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Sync posts from a public test API
python main.py sync --config examples/jsonplaceholder_posts.yaml

# Check sync history
python main.py status

# Preview synced rows
python main.py query --table posts --limit 5
```

## Incremental sync demo

```bash
# First run — fetches all records
python main.py sync --config examples/github_repos.yaml
# → {"fetched": 6, "upserted": 6, "cursor": "2024-12-01T..."}

# Second run — only fetches records updated since last cursor
python main.py sync --config examples/github_repos.yaml
# → {"fetched": 0, "upserted": 0, "cursor": "2024-12-01T..."}

# Force full re-fetch
python main.py sync --config examples/github_repos.yaml --full-refresh
```

## YAML config format

```yaml
name: my_api           # Unique source identifier (used as cursor key)
base_url: https://api.example.com
endpoint: /v1/orders
table: orders          # SQLite table name
id_field: order_id     # Primary key field for deduplication
cursor_field: updated_at
page_size: 100
timeout: 30
headers:
  Authorization: "Bearer ${API_TOKEN}"
params:
  status: active
```

## Running tests

```bash
pytest tests/ -v
# 30 passed
```

## Architecture decisions

**Why SQLite?** Zero-dependency local storage that works without a server. The `INSERT OR REPLACE` pattern gives idempotent upserts without a separate UPDATE path.

**Why YAML configs instead of code?** Adding a new API source is a config change, not a code change — no deployment needed, and non-engineers can add sources.

**Why cursor over full refresh?** For large datasets (100k+ records), re-fetching everything on every run is expensive and slow. A cursor lets the pipeline run frequently (every few minutes) without hammering the source API.

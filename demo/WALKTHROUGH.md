# 5-Minute Demo Walkthrough

## Goal

Show a buyer that the project can validate a customer-specific config, run a sync job, and inspect the resulting state without any code changes.

## Local flow

1. Create a virtual environment and install the project.
2. Copy `.env.example` values into your shell.
3. Validate the example customer config:

```bash
api-sync validate-config --config examples/customer_orders.yaml
```

4. Run a live sync against the public example source:

```bash
api-sync sync --config examples/jsonplaceholder_posts.yaml --db demo/public-demo.db
```

5. Inspect status and rows:

```bash
api-sync status --db demo/public-demo.db
api-sync query --db demo/public-demo.db --table posts --format table
```

## Docker flow

1. Build the demo image:

```bash
make demo-build
```

2. Run the public example in a container:

```bash
make demo-run
```

## What to point out

- The request contract is fully configuration-driven.
- Secrets come from environment variables, not committed files.
- The database schema evolves automatically when the payload grows.
- Operators can validate configs and inspect sync state from the CLI.
- The customer-style config is illustrative; the public example is there for a frictionless live demo.

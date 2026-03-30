PYTHON ?= python3
VENV_PYTHON ?= ./.venv/bin/python
PIP ?= ./.venv/bin/pip
IMAGE ?= api-sync-pipeline-demo

.PHONY: install test lint demo-build demo-run

install:
	python3 -m venv .venv
	$(PIP) install -e ".[dev]"

test:
	$(VENV_PYTHON) -m pytest -q

lint:
	$(VENV_PYTHON) -m ruff check .

demo-build:
	docker build -t $(IMAGE) .

demo-run:
	docker run --rm -v $(PWD):/workspace -w /workspace $(IMAGE) sync --config examples/jsonplaceholder_posts.yaml --db demo/docker-demo.db

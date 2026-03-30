FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md main.py /app/
COPY api_sync /app/api_sync
COPY examples /app/examples
COPY demo /app/demo

RUN pip install --no-cache-dir .

ENTRYPOINT ["api-sync"]
CMD ["--help"]

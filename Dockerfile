FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends cron ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY scripts ./scripts
COPY web ./web
COPY data ./data
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY docker/nightly.sh /usr/local/bin/nightly.sh

RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/nightly.sh

EXPOSE 8080

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
#!/usr/bin/env sh
set -eu

cd /app

echo "[$(date -Iseconds)] Starting nightly parcel refresh"
python3 scripts/fetch_parcels.py --output data/plain_city_parcels.geojson

if [ "${SEND_TELEGRAM:-0}" = "1" ]; then
  python3 scripts/detect_changes.py \
    --current data/plain_city_parcels.geojson \
    --baseline data/plain_city_parcels_last.geojson \
    --summary data/plain_city_changes_summary.json \
    --send-telegram
else
  python3 scripts/detect_changes.py \
    --current data/plain_city_parcels.geojson \
    --baseline data/plain_city_parcels_last.geojson \
    --summary data/plain_city_changes_summary.json
fi

echo "[$(date -Iseconds)] Nightly parcel refresh complete"

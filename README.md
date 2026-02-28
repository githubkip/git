# Plain City Parcel Monitor

Public-data parcel monitoring and map viewer for **Plain City, Utah**.

This project:
- Fetches parcel polygons intersecting Plain City boundary
- Saves them to `data/plain_city_parcels.geojson`
- Detects adds/removes/changes vs last snapshot
- Optionally sends Telegram summary alerts
- Serves a web map UI from `web/index.html`

---

## Data Sources

### Parcel dataset (ArcGIS)
- Weber County Assessor FeatureServer:
  - Service: `assessor/Assessed_Values_Map`
  - Layer 0 URL:
  - `https://maps.webercountyutah.gov/arcgis/rest/services/assessor/Assessed_Values_Map/FeatureServer/0`

### Plain City boundary dataset (ArcGIS)
- Weber EOC city boundaries MapServer:
  - Service: `cities/weber_eoc_city_boundaries`
  - Layer 0 URL:
  - `https://maps.webercountyutah.gov/arcgis/rest/services/cities/weber_eoc_city_boundaries/MapServer/0`

---

## Spatial Filtering Method

`fetch_parcels.py` uses a two-stage ArcGIS query flow:

1. Query city boundaries for `NAME='Plain City'` and retrieve the boundary polygon geometry.
2. Query parcel layer with:
   - `geometryType=esriGeometryPolygon`
   - `spatialRel=esriSpatialRelIntersects`
   - the Plain City geometry as the input geometry

To avoid ArcGIS transfer limits/paging inconsistencies:
- Script first gets a complete `returnIdsOnly=true` object ID set
- Then fetches parcels in chunks by `objectIds` (stable batching)
- Exports final combined results as GeoJSON (`outSR=4326`)

---

## Repository Structure

- `scripts/fetch_parcels.py` — download + spatial filter parcels
- `scripts/detect_changes.py` — compare current vs baseline snapshot and summarize changes
- `web/index.html` — Leaflet parcel map UI with popups + search
- `data/` — generated parcel snapshots and change summary files
- `Dockerfile` / `docker-compose.yml` — containerized deployment
- `docker/nightly.sh` — nightly refresh + change detection runner
- `docker/entrypoint.sh` — cron + static server startup

---

## Local Setup (without Docker)

Requirements:
- Python 3.10+
- Internet access to ArcGIS endpoints

Run:

```bash
python3 scripts/fetch_parcels.py --output data/plain_city_parcels.geojson
python3 scripts/detect_changes.py \
  --current data/plain_city_parcels.geojson \
  --baseline data/plain_city_parcels_last.geojson \
  --summary data/plain_city_changes_summary.json
python3 -m http.server 8080 --directory .
```

Then open:
- `http://localhost:8080/web/`

---

## Docker Setup (Local)

1. Build + run:

```bash
docker compose up -d --build
```

2. Open map:
- `http://localhost:8080/web/`

3. Logs:

```bash
docker logs -f plain-city-parcels
```

4. Cron logs (inside container):

```bash
docker exec -it plain-city-parcels sh -c 'tail -f /var/log/cron.log'
```

---

## EC2 Ubuntu Deployment Instructions

### 1) Launch EC2
- Ubuntu 22.04 or newer
- Open inbound port for web UI (example `8080`) in Security Group
- SSH (22) open to your IP

### 2) Install Docker + Compose plugin

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo $VERSION_CODENAME) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER
newgrp docker
```

### 3) Clone repo + configure

```bash
git clone <your-repo-url>
cd <repo-folder>
cp .env.example .env 2>/dev/null || true
```

Set environment variables (in `.env` or shell):

```bash
PORT=8080
TZ=America/Denver
CRON_SCHEDULE=15 2 * * *
RUN_ON_STARTUP=1
SEND_TELEGRAM=0
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

### 4) Start service

```bash
docker compose up -d --build
```

### 5) Verify

```bash
docker ps
docker logs plain-city-parcels --tail 100
```

Visit:
- `http://<EC2_PUBLIC_IP>:8080/web/`

---

## Telegram Alerts Configuration

`detect_changes.py` can send summary alerts via Telegram Bot API.

Set:
- `SEND_TELEGRAM=1`
- `TELEGRAM_BOT_TOKEN=<bot_token>`
- `TELEGRAM_CHAT_ID=<chat_id>`

Then nightly runs (or manual run with `--send-telegram`) will send summary messages.

Manual test:

```bash
python3 scripts/detect_changes.py \
  --current data/plain_city_parcels.geojson \
  --baseline data/plain_city_parcels_last.geojson \
  --summary data/plain_city_changes_summary.json \
  --send-telegram
```

By default, with watchlist mode enabled, Telegram alerts are skipped when there are no watched parcel changes.
Use `--send-when-no-changes` if you want an always-send heartbeat style alert.

---

## Watchlist: Notify Only for Specific Parcels

To track only selected parcels, create:
- `data/watched_parcels.txt`

Format:
- one parcel ID per line
- blank lines allowed
- `#` comments supported

Example starter file:
- `data/watched_parcels.txt.example`

When `data/watched_parcels.txt` exists, `detect_changes.py` filters adds/removes/changes to watched IDs only.
Summary output includes watchlist scope + size.

---

## Web Map Features

- Loads `data/plain_city_parcels.geojson`
- Renders parcel polygons in Leaflet
- Click popup shows:
  - `parcel_id` (`PARCEL_ID`)
  - available address fields (`STREET`, `CITY_STATE`, `ZIPCODE`, `PROP_STREET`, `PROP_CITY`, `PROP_ZIP`)
  - owner/mailing name field when present (`NAME_ONE`)
- Search supports parcel ID, owner name, or address string matches
- Title displayed: **"Plain City, UT Parcel Map (Public Data)"**

---

## Telegram Query Bot (Inbound Commands)

A companion polling bot is included:
- `scripts/telegram_query_bot.py`
- Compose service: `plain-city-telegram-bot`

Start services:

```bash
docker compose up -d --build
```

Supported commands:
- `/help`
- `/parcel <PARCEL_ID>`
- `/house <house number or address fragment>`
- `/changes`
- `/change <PARCEL_ID>`
- `/watched`

### `/house` interactive behavior

- Bot searches parcel addresses using `PROP_STREET`
- If multiple results, returns first 10 matches as inline buttons
- User taps a match, bot replies with full parcel details for that parcel ID

---

## Limitations

- Parcel data does **NOT** indicate who lives there.
- Owner name may not be included in free/public datasets.
- Change detection reflects **dataset changes**, not necessarily new residents.
- Source datasets can change schema/availability without notice.

---

## Troubleshooting

### 1) ArcGIS paging / transfer limits
Symptoms:
- Missing features
- Inconsistent counts between runs

Fix:
- Use `returnIdsOnly=true` first, then chunk by object IDs (already implemented)
- Keep chunk size moderate (`--chunk-size 300-600`)

### 2) Geometry filtering returns zero features
Symptoms:
- `Found 0 parcels intersecting Plain City boundary`

Checks:
- Boundary query still returns `Plain City`
- Ensure `inSR` matches boundary geometry SR (current script uses 3560)
- Re-run manually and inspect response payload errors

### 3) Large dataset handling / performance
Symptoms:
- Long run times
- Timeouts

Fix:
- Reduce chunk size (`--chunk-size 200`)
- Add slight pause between chunks (`--pause 0.1`)
- Run on a larger EC2 instance if needed

### 4) Cron not running
Checks:
- `docker logs plain-city-parcels`
- `docker exec -it plain-city-parcels sh -c 'cat /etc/cron.d/plain-city-parcels'`
- `docker exec -it plain-city-parcels sh -c 'tail -n 200 /var/log/cron.log'`

### 5) Telegram alerts not sending
Checks:
- `SEND_TELEGRAM=1`
- Correct `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
- Bot has permission to message chat/user
- Inspect output from `detect_changes.py --send-telegram`

---

## First Run Expectations

On first successful fetch run, you should get:
- `data/plain_city_parcels.geojson`

On first change detection run:
- Baseline file initialized (`data/plain_city_parcels_last.geojson`)
- Subsequent runs provide add/remove/change summaries

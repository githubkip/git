#!/usr/bin/env sh
set -eu

CRON_SCHEDULE="${CRON_SCHEDULE:-15 2 * * *}"
PORT="${PORT:-8080}"
RUN_ON_STARTUP="${RUN_ON_STARTUP:-1}"

mkdir -p /var/log
: > /var/log/cron.log

cat >/etc/cron.d/plain-city-parcels <<EOF
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
${CRON_SCHEDULE} root /usr/local/bin/nightly.sh >> /var/log/cron.log 2>&1
EOF

chmod 0644 /etc/cron.d/plain-city-parcels
crontab /etc/cron.d/plain-city-parcels

if [ "$RUN_ON_STARTUP" = "1" ]; then
  echo "Running initial parcel refresh..."
  /usr/local/bin/nightly.sh || true
fi

cron

echo "Serving web root at /app on port ${PORT}"
exec python3 -m http.server "${PORT}" --directory /app

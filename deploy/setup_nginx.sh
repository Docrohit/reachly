#!/usr/bin/env bash
# Install nginx site for Reachly dashboard (reach.hygaar.com → :8765).
# Run on the app server: sudo bash /opt/reachly/deploy/setup_nginx.sh
set -euo pipefail

CONF_SRC="/opt/reachly/deploy/nginx/reach.hygaar.com.conf"
CONF_DST="/etc/nginx/sites-available/reach.hygaar.com.conf"

if [ ! -f "$CONF_SRC" ]; then
  echo "Missing $CONF_SRC — sync /opt/reachly first."
  exit 1
fi

cp "$CONF_SRC" "$CONF_DST"
ln -sf "$CONF_DST" /etc/nginx/sites-enabled/reach.hygaar.com.conf
nginx -t
systemctl reload nginx
echo "OK: reach.hygaar.com → 127.0.0.1:8765"
echo "Ensure DNS/ALB routes reach.hygaar.com to this host (port 80)."

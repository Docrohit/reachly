#!/usr/bin/env bash
# Install an explicitly reviewed personal Reachly nginx configuration.
set -euo pipefail
: "${REACHLY_NGINX_CONFIG:?Set the path to the reviewed personal nginx config}"
test -f "$REACHLY_NGINX_CONFIG"
cp "$REACHLY_NGINX_CONFIG" /etc/nginx/sites-available/reachly-personal
ln -sf /etc/nginx/sites-available/reachly-personal /etc/nginx/sites-enabled/reachly-personal
nginx -t
systemctl reload nginx

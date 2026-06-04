#!/usr/bin/env bash
# =====================================================================
# Reachly hosted SaaS bootstrap (Ubuntu/Debian).
# Installs the multi-tenant FastAPI product under /opt/reachly-saas.
#
# Usage (run from copied source, e.g. /tmp/reachly):
#   sudo bash deploy/install_saas_on_server.sh
# =====================================================================
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/reachly-saas}"
SERVICE_USER="${SERVICE_USER:-reachly}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo ">> Reachly SaaS install starting"
echo "   source : $SRC_DIR"
echo "   target : $APP_DIR"

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  echo ">> creating service user '$SERVICE_USER'"
  useradd --system --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

if ! command -v python3 >/dev/null 2>&1; then
  apt-get update && apt-get install -y python3 python3-venv python3-pip
fi

echo ">> syncing code to $APP_DIR"
mkdir -p "$APP_DIR"
rsync -a --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '.env' \
  --exclude '.reachly_data' \
  --exclude 'reachly_media' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  "$SRC_DIR/" "$APP_DIR/"

echo ">> creating virtualenv + installing requirements"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip -q
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

mkdir -p "$APP_DIR/data/media"
if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  echo ">> created $APP_DIR/.env from template — set production secrets before starting"
fi

chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR"
chmod 600 "$APP_DIR/.env"

echo ">> installing systemd unit reachly-saas.service"
cp "$APP_DIR/deploy/reachly-saas.service" /etc/systemd/system/reachly-saas.service
systemctl daemon-reload

echo ">> installing nginx vhost when nginx is present"
if command -v nginx >/dev/null 2>&1; then
  if [ -f /etc/letsencrypt/live/reachly.nftforger.com/fullchain.pem ]; then
    cp "$APP_DIR/deploy/nginx/reachly.nftforger.com.ssl.conf" /etc/nginx/sites-available/reachly.nftforger.com
  else
    cp "$APP_DIR/deploy/nginx/reachly.nftforger.com.conf" /etc/nginx/sites-available/reachly.nftforger.com
  fi
  ln -sf /etc/nginx/sites-available/reachly.nftforger.com /etc/nginx/sites-enabled/reachly.nftforger.com
  nginx -t
  systemctl reload nginx
fi

echo ""
echo "============================================================"
echo " Reachly SaaS installed at $APP_DIR"
echo " Next:"
echo "   1) set production secrets in $APP_DIR/.env"
echo "   2) sudo systemctl enable --now reachly-saas"
echo "   3) curl http://127.0.0.1:8050/healthz"
echo "============================================================"

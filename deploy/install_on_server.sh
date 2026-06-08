#!/usr/bin/env bash
# =====================================================================
# Reachly — server bootstrap (Ubuntu/Debian).
# Installs Reachly as its OWN isolated service under /opt/reachly.
# Does NOT touch hdb_backend or its CodeDeploy pipeline.
#
# Usage (run from the copied source, e.g. /tmp/reachly):
#   sudo bash deploy/install_on_server.sh
# =====================================================================
set -euo pipefail

APP_DIR="/opt/reachly"
SERVICE_USER="reachly"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USE_BROWSER="${USE_BROWSER:-0}"   # set USE_BROWSER=1 to install Playwright + Chromium
ENABLE_SERVICE="${ENABLE_SERVICE:-1}" # set ENABLE_SERVICE=0 to install without enabling systemd

echo ">> Reachly install starting"
echo "   source : $SRC_DIR"
echo "   target : $APP_DIR"

# --- system user (no login shell) ---
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  echo ">> creating service user '$SERVICE_USER'"
  useradd --system --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

# --- python ---
if ! command -v python3 >/dev/null 2>&1; then
  apt-get update && apt-get install -y python3 python3-venv python3-pip
fi

# --- copy code ---
echo ">> syncing code to $APP_DIR"
mkdir -p "$APP_DIR"
rsync -a --exclude '.venv' --exclude '.git' --exclude '__pycache__' \
      --exclude '*.pyc' --exclude '.reachly_data' "$SRC_DIR/" "$APP_DIR/"

# --- virtualenv + deps ---
echo ">> creating virtualenv + installing requirements"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip -q
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

if [ "$USE_BROWSER" = "1" ]; then
  echo ">> installing Playwright Chromium (browser mode)"
  "$APP_DIR/.venv/bin/python" -m playwright install --with-deps chromium
fi

# --- .env (don't overwrite an existing one) ---
if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  echo ">> created $APP_DIR/.env from template — EDIT IT before going live"
fi
chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR"
chmod 600 "$APP_DIR/.env"

# --- systemd service ---
echo ">> installing systemd unit reachly-agent.service"
cat > /etc/systemd/system/reachly-agent.service <<UNIT
[Unit]
Description=Reachly thought-leadership agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/.venv/bin/python -m reachly.runner run
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
if [ "$ENABLE_SERVICE" = "1" ]; then
  echo ">> enabling reachly-agent.service"
  systemctl enable reachly-agent.service
fi

echo ""
echo "============================================================"
echo " Reachly installed at $APP_DIR"
echo " Next:"
echo "   1) sudo nano $APP_DIR/.env        # business info + keys"
echo "   2) sudo -u $SERVICE_USER $APP_DIR/.venv/bin/python -m reachly.runner preview"
echo "   3) set DRY_RUN=\"no\" in .env, then:"
echo "      sudo systemctl restart reachly-agent"
echo "      sudo journalctl -u reachly-agent -f"
echo ""
echo " For headless browser mode, re-run with: USE_BROWSER=1 sudo -E bash $0"
echo "============================================================"

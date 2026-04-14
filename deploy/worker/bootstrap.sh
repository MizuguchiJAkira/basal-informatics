#!/usr/bin/env bash
# One-shot Droplet bootstrap for the Strecker worker.
#
# Run this on a fresh Ubuntu 22.04+ Droplet as root:
#   curl -fsSL https://raw.githubusercontent.com/MizuguchiJAkira/strecker/main/deploy/worker/bootstrap.sh | bash
#
# Or locally:
#   scp -r deploy/ root@<droplet>:/tmp/
#   ssh root@<droplet> bash /tmp/deploy/worker/bootstrap.sh
#
# What it does:
#   1. Installs Docker
#   2. Clones the repo to /opt/strecker
#   3. Creates /etc/strecker/worker.env (you fill in credentials)
#   4. Builds Dockerfile.worker
#   5. Installs + enables strecker-worker.service
#
# After it finishes, edit /etc/strecker/worker.env with your DATABASE_URL and
# Spaces credentials, then `systemctl start strecker-worker`.

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/MizuguchiJAkira/strecker.git}"
REPO_DIR="${REPO_DIR:-/opt/strecker}"
BRANCH="${BRANCH:-main}"

echo "==> Installing system packages"
apt-get update
apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg git

echo "==> Installing Docker"
if ! command -v docker >/dev/null 2>&1; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io
fi

echo "==> Cloning Strecker -> $REPO_DIR"
if [ -d "$REPO_DIR/.git" ]; then
    git -C "$REPO_DIR" fetch --depth 1 origin "$BRANCH"
    git -C "$REPO_DIR" checkout "$BRANCH"
    git -C "$REPO_DIR" reset --hard "origin/$BRANCH"
else
    git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$REPO_DIR"
fi

echo "==> Setting up /etc/strecker/worker.env"
mkdir -p /etc/strecker
if [ ! -f /etc/strecker/worker.env ]; then
    cat > /etc/strecker/worker.env <<'EOF'
# --- Strecker worker env ---
# Fill these in before starting the service.

# Shared Postgres (same URL as App Platform web component)
DATABASE_URL=

# DigitalOcean Spaces (shared with web)
SPACES_BUCKET=
SPACES_REGION=nyc3
SPACES_ENDPOINT=https://nyc3.digitaloceanspaces.com
SPACES_KEY=
SPACES_SECRET=

# Worker tuning
WORKER_POLL_SECS=10
WORKER_STALE_MINS=60
LOG_LEVEL=INFO
EOF
    chmod 600 /etc/strecker/worker.env
    echo "    Created /etc/strecker/worker.env — EDIT IT before starting the service."
else
    echo "    /etc/strecker/worker.env already exists, leaving it alone."
fi

echo "==> Building worker image"
cd "$REPO_DIR"
docker build -f Dockerfile.worker -t strecker-worker:latest .

echo "==> Installing systemd unit"
cp "$REPO_DIR/deploy/worker/strecker-worker.service" /etc/systemd/system/strecker-worker.service
systemctl daemon-reload
systemctl enable strecker-worker.service

echo
echo "==================================================================="
echo "  Bootstrap complete."
echo
echo "  Next:"
echo "    1. Edit /etc/strecker/worker.env and fill in DATABASE_URL + Spaces creds"
echo "    2. systemctl start strecker-worker"
echo "    3. journalctl -fu strecker-worker        # watch logs"
echo
echo "  To update the worker later:"
echo "    bash $REPO_DIR/deploy/worker/update.sh"
echo "==================================================================="

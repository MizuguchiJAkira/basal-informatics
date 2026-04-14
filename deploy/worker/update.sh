#!/usr/bin/env bash
# Pull latest code, rebuild the worker image, restart the service.
# Run on the worker Droplet as root.
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/strecker}"
BRANCH="${BRANCH:-main}"

echo "==> git pull"
git -C "$REPO_DIR" fetch --depth 1 origin "$BRANCH"
git -C "$REPO_DIR" reset --hard "origin/$BRANCH"

echo "==> docker build"
cd "$REPO_DIR"
docker build -f Dockerfile.worker -t strecker-worker:latest .

echo "==> systemctl restart"
systemctl restart strecker-worker
sleep 2
systemctl --no-pager status strecker-worker | head -n 20

echo
echo "Done. Watch logs with:  journalctl -fu strecker-worker"

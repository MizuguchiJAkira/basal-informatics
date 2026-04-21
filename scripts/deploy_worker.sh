#!/usr/bin/env bash
# scripts/deploy_worker.sh — idempotent deploy of the Strecker ML worker.
#
# Runs ON THE WORKER DROPLET (/opt/strecker checkout). Idempotent and
# re-runnable: a git-pull with nothing new + a rebuild with a warm
# cache is a few seconds and a no-op container restart.
#
# Order of operations matters:
#   1. git pull — bring in new code + new migration files to the host
#   2. docker build — produce a new image that SEES the new migration
#      files (container's /app is a snapshot of the host at build time)
#   3. migrate.py INSIDE THE NEW IMAGE — now sees the new files and
#      applies any pending DDL
#   4. systemctl restart — cycle the container so the service runs on
#      the new image
#
# Earlier versions of this playbook swapped steps 2 and 3. That meant
# migrate.py ran inside the OLD image, couldn't see the new migration
# file, and silently reported "up to date" — leaving the schema wider
# than the database. This script fences that off.
#
# Usage (on the Droplet as root):
#   cd /opt/strecker && ./scripts/deploy_worker.sh

set -euo pipefail

cd "$(dirname "$0")/.."
REPO_ROOT=$(pwd)

echo "=== 1/4  git pull ==="
git pull --rebase
git log --oneline -3

echo
echo "=== 2/4  docker build (new image sees new migrations) ==="
docker build -f Dockerfile.worker -t strecker-worker:latest . 2>&1 | tail -6

echo
echo "=== 3/4  migrate (inside a fresh container off the NEW image) ==="
# Spin up a one-shot container off the freshly-built image to run the
# migrator. This is the ONLY safe place for the migrator to run —
# guaranteed to see the migration files we just pulled.
docker run --rm \
    --env-file /etc/strecker/worker.env \
    strecker-worker:latest \
    python scripts/migrate.py

echo
echo "=== 4/4  restart service ==="
systemctl restart strecker-worker
sleep 4
docker ps | grep strecker-worker
echo
echo "=== fresh worker log head ==="
docker logs --tail 10 strecker-worker 2>&1

echo
echo "Deploy complete."

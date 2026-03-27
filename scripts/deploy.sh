#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVER="${DEPLOY_SERVER:-}"

if [ -z "$SERVER" ]; then
    echo "Usage: DEPLOY_SERVER=user@host ./scripts/deploy.sh"
    exit 1
fi

echo "=== Deploying Frey to $SERVER ==="

# 1. Sync memory from server (preserve daily logs)
echo "Syncing memory from server..."
rsync -avz "$SERVER:~/frey/workspace/memory/" "$REPO_ROOT/workspace/memory/" 2>/dev/null || true

# 2. Sync workspace + skills to server
echo "Syncing workspace and skills to server..."
rsync -avz --exclude='memory/' "$REPO_ROOT/workspace/" "$SERVER:~/frey/workspace/"
rsync -avz "$REPO_ROOT/skills/" "$SERVER:~/frey/skills/"
rsync -avz "$REPO_ROOT/docker/docker-compose.yml" "$SERVER:~/frey/docker/"

# 3. Restart fortnox service
echo "Restarting fortnox service..."
ssh "$SERVER" 'sudo systemctl restart frey-fortnox.service' 2>/dev/null || echo "  (skipped - service not configured)"

# 4. Rebuild and restart OpenClaw
echo "Restarting OpenClaw..."
ssh "$SERVER" 'cd ~/frey/docker && docker compose pull && docker compose up -d' 2>/dev/null || echo "  (skipped - docker not configured)"

echo "Deploy complete."

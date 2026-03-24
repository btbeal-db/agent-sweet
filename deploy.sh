#!/usr/bin/env bash
set -euo pipefail

# ── Agent Builder Deploy Script ──────────────────────────────────────────────
# Usage:
#   ./deploy.sh              # build + sync files + redeploy app on dev
#   ./deploy.sh prod         # same for prod target
#   ./deploy.sh dev --clean  # clear stale state (when switching workspaces)
#   ./deploy.sh dev --init   # first-time: creates app + provisions compute
#
# Normal flow (after first init):
#   1. Builds frontend → backend/static/
#   2. bundle deploy   → syncs files to workspace + updates app config
#   3. apps deploy     → tells the running app to pick up new code (no compute restart)

TARGET="${1:-dev}"
CLEAN=false
INIT=false

for arg in "$@"; do
  case "$arg" in
    --clean) CLEAN=true ;;
    --init)  INIT=true ;;
  esac
done

APP_NAME="agent-builder-${TARGET}"
echo "── Target: $TARGET  App: $APP_NAME"

# 1. Build frontend
echo "── Building frontend..."
(cd frontend && npm run build)

# 2. Optionally clear stale Terraform state (needed when switching workspaces)
STATE_FILE=".databricks/bundle/$TARGET/terraform/terraform.tfstate"
if [[ "$CLEAN" == true ]] && [[ -f "$STATE_FILE" ]]; then
  echo "── Clearing stale deployment state..."
  rm "$STATE_FILE"
fi

# 3. Sync files + update app config (scopes, env vars, etc.)
echo "── Syncing bundle..."
databricks bundle deploy -t "$TARGET"

# 4. Trigger app redeployment
BUNDLE_PATH=$(databricks bundle summary -t "$TARGET" 2>&1 | grep "Path:" | awk '{print $2}')
SOURCE_PATH="${BUNDLE_PATH}/files"

if [[ "$INIT" == true ]]; then
  # First time only: creates the app resource and provisions compute
  echo "── Initializing app (first-time setup)..."
  databricks bundle run agent_builder -t "$TARGET"
else
  # Redeploy: tells the running app to pick up new code — no compute restart
  echo "── Redeploying app..."
  databricks apps deploy "$APP_NAME" --source-code-path "$SOURCE_PATH"
fi

echo "── Done!"

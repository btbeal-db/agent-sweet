#!/usr/bin/env bash
set -euo pipefail

# ── Agent Builder — Initial Setup Script ─────────────────────────────────────
#
# Run this ONCE to set up the infrastructure for deploying agents.
# After setup, deploy code changes from Git in the Databricks Apps UI.
#
# Usage:
#   ./deploy.sh --profile MY_PROFILE
#
# Prerequisites:
#   1. Databricks CLI v0.230+ authenticated to your workspace
#   2. Node.js 18+ and npm
#   3. Python 3.10+ and uv
#   4. DEPLOY_CATALOG and DEPLOY_SCHEMA set in app.yaml
#
# What this script does:
#   1. Builds the frontend
#   2. Uploads the deploy notebook to the workspace
#   3. Deploys the bundle (creates the Job + App + wires resources)
#   4. Sets user API scopes (workaround: SDK doesn't propagate these)
#   5. Grants the app's SP access to the configured catalog/schema
#   6. Initializes the app
#
# After this, deploy code changes by pushing to Git and deploying from
# the Databricks Apps UI. The Job, resources, scopes, and grants persist.

# ── Prerequisites ────────────────────────────────────────────────────────────
command -v databricks >/dev/null 2>&1 || { echo "ERROR: 'databricks' CLI not found."; exit 1; }
command -v node >/dev/null 2>&1 || { echo "ERROR: 'node' not found. Install Node.js 18+."; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "ERROR: 'npm' not found."; exit 1; }

TARGET="${1:-dev}"
PROFILE=""
CLEAN=false

if [[ "${1:-}" == --* ]]; then
  TARGET="dev"
fi

args=("$@")
for i in "${!args[@]}"; do
  case "${args[$i]}" in
    --clean) CLEAN=true ;;
    --profile=*) PROFILE="${args[$i]#--profile=}" ;;
    --profile)   [[ $((i+1)) -lt ${#args[@]} ]] && PROFILE="${args[$((i+1))]}" ;;
  esac
done

if [[ -n "$PROFILE" ]]; then
  export DATABRICKS_CONFIG_PROFILE="$PROFILE"
  echo "── Using Databricks CLI profile: $PROFILE"
elif [[ -z "${DATABRICKS_CONFIG_PROFILE:-}" ]]; then
  echo "ERROR: No profile specified. Use --profile <name> or set DATABRICKS_CONFIG_PROFILE."
  exit 1
fi

APP_NAME="agent-builder-${TARGET}"
echo "── Target: $TARGET  App: $APP_NAME"

# ── 1. Build frontend ───────────────────────────────────────────────────────
echo "── Building frontend..."
(cd frontend && [[ -d node_modules ]] || npm install && npm run build)

# ── 2. Ensure requirements-serving.txt exists ────────────────────────────────
if [[ ! -f requirements-serving.txt ]]; then
  echo "── Generating requirements-serving.txt..."
  uv pip compile pyproject.toml -o requirements-serving.txt --python-version 3.10
fi

# ── 3. Optionally clear stale Terraform state ────────────────────────────────
STATE_FILE=".databricks/bundle/$TARGET/terraform/terraform.tfstate"
if [[ "$CLEAN" == true ]] && [[ -f "$STATE_FILE" ]]; then
  echo "── Clearing stale deployment state..."
  rm "$STATE_FILE"
fi

# ── 4. Upload deploy notebook ────────────────────────────────────────────────
echo "── Uploading deploy notebook..."
databricks workspace mkdirs /Shared/agent-builder 2>/dev/null || true
databricks workspace import /Shared/agent-builder/deploy_notebook \
  --file backend/deploy_notebook.py \
  --language PYTHON \
  --format SOURCE \
  --overwrite

# ── 5. Deploy bundle (creates Job + App + wires resources) ───────────────────
echo "── Deploying bundle..."
databricks bundle deploy -t "$TARGET"

# ── 6. Set user API scopes ───────────────────────────────────────────────────
echo "── Setting user API scopes..."
databricks api patch /api/2.0/apps/"$APP_NAME" --json '{
  "user_api_scopes": [
    "catalog.catalogs:read",
    "catalog.schemas:read",
    "catalog.tables:read",
    "dashboards.genie",
    "serving.serving-endpoints",
    "serving.serving-endpoints-data-plane",
    "sql",
    "vectorsearch.vector-search-endpoints",
    "vectorsearch.vector-search-indexes"
  ]
}' > /dev/null 2>&1 || echo "  (could not set scopes — set manually in Apps UI)"

# ── 7. Grant app's SP access to catalog/schema ──────────────────────────────
CATALOG=$(python3 -c "
import yaml
with open('app.yaml') as f:
    d = yaml.safe_load(f)
for e in d.get('env', []):
    if e['name'] == 'DEPLOY_CATALOG':
        print(e['value'])
        break
" 2>/dev/null || echo "")

SCHEMA=$(python3 -c "
import yaml
with open('app.yaml') as f:
    d = yaml.safe_load(f)
for e in d.get('env', []):
    if e['name'] == 'DEPLOY_SCHEMA':
        print(e['value'])
        break
" 2>/dev/null || echo "")

if [[ -n "$CATALOG" ]] && [[ "$CATALOG" != "CHANGE_ME" ]] && [[ -n "$SCHEMA" ]] && [[ "$SCHEMA" != "CHANGE_ME" ]]; then
  APP_SP_CLIENT_ID=$(databricks apps get "$APP_NAME" 2>/dev/null | python3 -c "
import sys, json
print(json.load(sys.stdin).get('service_principal_client_id', ''))
" 2>/dev/null || echo "")

  if [[ -n "$APP_SP_CLIENT_ID" ]]; then
    echo "── Granting app SP access to ${CATALOG}.${SCHEMA}..."
    databricks api patch "/api/2.0/unity-catalog/permissions/catalog/${CATALOG}" --json "{
      \"changes\": [{
        \"principal\": \"${APP_SP_CLIENT_ID}\",
        \"add\": [\"USE_CATALOG\"]
      }]
    }" > /dev/null 2>&1 || echo "  (could not grant USE_CATALOG)"

    databricks api patch "/api/2.0/unity-catalog/permissions/schema/${CATALOG}.${SCHEMA}" --json "{
      \"changes\": [{
        \"principal\": \"${APP_SP_CLIENT_ID}\",
        \"add\": [\"USE_SCHEMA\", \"CREATE_MODEL\"]
      }]
    }" > /dev/null 2>&1 || echo "  (could not grant USE_SCHEMA/CREATE_MODEL)"
  fi
else
  echo "  WARNING: Set DEPLOY_CATALOG and DEPLOY_SCHEMA in app.yaml before running this script."
fi

# ── 8. Initialize app ───────────────────────────────────────────────────────
echo "── Initializing app..."
databricks bundle run agent_builder -t "$TARGET"

echo ""
echo "══════════════════════════════════════════════════════════════════"
echo "  Setup complete!"
echo ""
echo "  App URL: $(databricks apps get "$APP_NAME" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('url','(check workspace)'))" 2>/dev/null || echo '(check workspace)')"
echo ""
echo "  Next steps:"
echo "    1. Open the app and verify it works"
echo "    2. For code changes: push to Git, deploy from the Apps UI"
echo "    3. The deploy Job, scopes, and grants persist across deploys"
echo "══════════════════════════════════════════════════════════════════"

#!/usr/bin/env bash
set -euo pipefail

# ── Agent Builder — Admin Setup Script ──────────────────────────────────────
#
# Run this ONCE to set up the infrastructure for deploying agents.
# After setup, redeploy code changes from Git in the Databricks Apps UI,
# or re-run this script with --deploy-only to push a new git ref.
#
# Usage:
#   ./deploy.sh --profile MY_PROFILE --repo https://github.com/org/repo.git
#
# Prerequisites:
#   1. Databricks CLI v0.230+ authenticated to your workspace
#   2. Node.js 18+ and npm (for building the frontend)
#
# What this script does:
#   1. Creates the Databricks App (linked to the Agent Sweet Git repo)
#   2. Uploads the deploy notebook to the workspace
#   3. Creates the deploy Job
#   4. Wires the Job as an App resource
#   5. Sets user API scopes on the App
#   6. Deploys the App from the specified Git branch
#
# After this, deploy code changes by pushing to Git and deploying from
# the Databricks Apps UI. The Job, resources, scopes, and grants persist.

# ── Defaults ────────────────────────────────────────────────────────────────
APP_NAME="agent-sweet"
GIT_BRANCH="main"
GIT_REPO="https://github.com/btbeal-db/agent-sweet.git"
PROFILE=""
DEPLOY_ONLY=false
NOTEBOOK_WORKSPACE_PATH="/Shared/agent-sweet/deploy_notebook"

# ── Parse arguments ─────────────────────────────────────────────────────────
args=("$@")
for i in "${!args[@]}"; do
  case "${args[$i]}" in
    --profile=*) PROFILE="${args[$i]#--profile=}" ;;
    --profile)   [[ $((i+1)) -lt ${#args[@]} ]] && PROFILE="${args[$((i+1))]}" ;;
    --repo=*)    GIT_REPO="${args[$i]#--repo=}" ;;
    --repo)      [[ $((i+1)) -lt ${#args[@]} ]] && GIT_REPO="${args[$((i+1))]}" ;;
    --branch=*)  GIT_BRANCH="${args[$i]#--branch=}" ;;
    --branch)    [[ $((i+1)) -lt ${#args[@]} ]] && GIT_BRANCH="${args[$((i+1))]}" ;;
    --app=*)     APP_NAME="${args[$i]#--app=}" ;;
    --app)       [[ $((i+1)) -lt ${#args[@]} ]] && APP_NAME="${args[$((i+1))]}" ;;
    --deploy-only) DEPLOY_ONLY=true ;;
  esac
done

# ── Validate ────────────────────────────────────────────────────────────────
command -v databricks >/dev/null 2>&1 || { echo "ERROR: 'databricks' CLI not found."; exit 1; }

if [[ -n "$PROFILE" ]]; then
  export DATABRICKS_CONFIG_PROFILE="$PROFILE"
  echo "── Using Databricks CLI profile: $PROFILE"
elif [[ -z "${DATABRICKS_CONFIG_PROFILE:-}" ]]; then
  echo "ERROR: No profile specified. Use --profile <name> or set DATABRICKS_CONFIG_PROFILE."
  exit 1
fi

echo "── App: $APP_NAME"
echo "── Git repo: $GIT_REPO"
echo "── Git branch: $GIT_BRANCH"

# ── Deploy-only mode: just push a new deployment ────────────────────────────
if [[ "$DEPLOY_ONLY" == true ]]; then
  echo "── Deploying from git branch: $GIT_BRANCH"
  databricks apps deploy "$APP_NAME" --json "{\"git_source\": {\"branch\": \"$GIT_BRANCH\"}}"
  echo "── Done!"
  exit 0
fi

# ── 1. Create App (linked to Git repo) ─────────────────────────────────────
echo "── Creating app '$APP_NAME'..."
if databricks apps get "$APP_NAME" > /dev/null 2>&1; then
  echo "  App already exists — skipping creation."
else
  databricks apps create --json "{
    \"name\": \"$APP_NAME\",
    \"git_repository\": {
      \"url\": \"$GIT_REPO\",
      \"provider\": \"gitHub\"
    }
  }"
  echo "  App created. Waiting for compute to start..."
  sleep 5
fi

# ── 2. Upload deploy notebook ───────────────────────────────────────────────
echo "── Uploading deploy notebook..."
databricks workspace mkdirs /Shared/agent-sweet 2>/dev/null || true
databricks workspace import "$NOTEBOOK_WORKSPACE_PATH" \
  --file backend/deploy_notebook.py \
  --language PYTHON \
  --format SOURCE \
  --overwrite

# ── 3. Create deploy Job ───────────────────────────────────────────────────
echo "── Creating deploy job..."
JOB_NAME="agent-builder-deploy"

# Check if job already exists
EXISTING_JOB_ID=$(databricks jobs list --output json 2>/dev/null | python3 -c "
import sys, json
jobs = json.load(sys.stdin).get('jobs', [])
for j in jobs:
    if j['settings']['name'] == '$JOB_NAME':
        print(j['job_id'])
        break
" 2>/dev/null || echo "")

if [[ -n "$EXISTING_JOB_ID" ]]; then
  echo "  Job already exists (ID: $EXISTING_JOB_ID) — skipping creation."
  JOB_ID="$EXISTING_JOB_ID"
else
  JOB_ID=$(databricks jobs create --json "{
    \"name\": \"$JOB_NAME\",
    \"tasks\": [{
      \"task_key\": \"deploy\",
      \"notebook_task\": {
        \"notebook_path\": \"$NOTEBOOK_WORKSPACE_PATH\"
      },
      \"environment_key\": \"default\"
    }],
    \"environments\": [{
      \"environment_key\": \"default\",
      \"spec\": {\"client\": \"1\"}
    }],
    \"max_concurrent_runs\": 20,
    \"queue\": {\"enabled\": true}
  }" | python3 -c "import sys, json; print(json.load(sys.stdin)['job_id'])")
  echo "  Created job (ID: $JOB_ID)"
fi

# ── 4. Wire Job as App resource ─────────────────────────────────────────────
echo "── Wiring deploy job as app resource..."
databricks api patch "/api/2.0/apps/$APP_NAME" --json "{
  \"resources\": [{
    \"name\": \"deploy-job\",
    \"job\": {
      \"id\": \"$JOB_ID\",
      \"permission\": \"CAN_MANAGE_RUN\"
    }
  }]
}" > /dev/null 2>&1 || echo "  (could not wire job resource — set manually in Apps UI)"

# ── 5. Set user API scopes ──────────────────────────────────────────────────
echo "── Setting user API scopes..."
databricks api patch "/api/2.0/apps/$APP_NAME" --json '{
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

# ── 6. Update app.yaml with Job ID (if changed) ────────────────────────────
CURRENT_JOB_ID=$(python3 -c "
import yaml
with open('app.yaml') as f:
    d = yaml.safe_load(f)
for e in d.get('env', []):
    if e['name'] == 'DEPLOY_JOB_ID':
        print(e['value'])
        break
" 2>/dev/null || echo "")

if [[ "$CURRENT_JOB_ID" != "$JOB_ID" ]]; then
  echo "── Updating DEPLOY_JOB_ID in app.yaml to $JOB_ID"
  python3 -c "
import yaml
with open('app.yaml') as f:
    d = yaml.safe_load(f)
found = False
for e in d.get('env', []):
    if e['name'] == 'DEPLOY_JOB_ID':
        e['value'] = '$JOB_ID'
        found = True
        break
if not found:
    d.setdefault('env', []).append({'name': 'DEPLOY_JOB_ID', 'value': '$JOB_ID'})
with open('app.yaml', 'w') as f:
    yaml.dump(d, f, default_flow_style=False, sort_keys=False)
  "
  echo "  NOTE: Commit and push this change, then redeploy to pick up the new Job ID."
fi

# ── 7. Deploy from Git ─────────────────────────────────────────────────────
echo "── Deploying app from git branch: $GIT_BRANCH"
databricks apps deploy "$APP_NAME" --json "{\"git_source\": {\"branch\": \"$GIT_BRANCH\"}}"

# ── Done ────────────────────────────────────────────────────────────────────
APP_URL=$(databricks apps get "$APP_NAME" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('url','(check workspace)'))" 2>/dev/null || echo "(check workspace)")

echo ""
echo "══════════════════════════════════════════════════════════════════"
echo "  Setup complete!"
echo ""
echo "  App URL: $APP_URL"
echo "  Deploy Job ID: $JOB_ID"
echo ""
echo "  Next steps:"
echo "    1. Open the app and verify it works"
echo "    2. For code changes: push to Git, deploy from the Apps UI"
echo "       or run: ./deploy.sh --profile $PROFILE --deploy-only"
echo "    3. The deploy Job, scopes, and grants persist across deploys"
echo "══════════════════════════════════════════════════════════════════"

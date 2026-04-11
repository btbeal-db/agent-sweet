# Agent Sweet

Visual drag-and-drop [LangGraph](https://langchain-ai.github.io/langgraph/) agent builder for Databricks. Build, preview, and deploy AI agents — no code required.

**Built-in node types:** LLM, Router, Vector Search, Genie, UC Function, Human Input

## Deploy

1. In your Databricks workspace, go to **Compute > Apps**
2. Click **Create App** and give it a name
3. Under **Git repository**, paste this repo's URL
4. Click **Deploy > From Git**, set the branch to `main`, and deploy

That's it. The app is live. See [Databricks Apps docs](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/deploy/#deploy-from-a-git-repository) for details.

## First-Time Setup

Each user completes a one-time setup before deploying agents. Open the app and navigate to the **Setup** page.

### Step 1: Create an experiment folder

In your Databricks workspace, create a folder under your user directory (e.g. `/Users/you@company.com/agent-sweet`). This is where your MLflow experiments will live.

### Step 2: Grant the app access

The Setup page will show the app's service principal name. Grant it **Can Manage** on your folder — the app will try to do this automatically, or show you manual instructions.

### Step 3: Validate

Click **Validate** on the Setup page. The app confirms it can write to your folder.

That's it. You're ready to build and deploy agents.

## Using the App

### Build

Drag nodes onto the canvas, wire them together, and configure each node. Define your agent's state model in the left panel.

### Preview

Click **Playground** to test your agent with live data. Previews use your own identity — you only see data you have access to.

### Deploy

Click **Deploy** and choose a deploy mode:

- **Log Only** — saves the agent as an MLflow model in your experiment folder. No PAT required. You can then register and deploy the model yourself from the Databricks UI (see [Deploy models from Model Registry](https://docs.databricks.com/en/machine-learning/manage-model-lifecycle/index.html)).
- **Log & Register** or **Full Deploy** — also registers in Unity Catalog and (optionally) creates a serving endpoint. These modes require a Personal Access Token (PAT).

**About your PAT:**
- Generate one at **Settings > Developer > Access tokens** in your Databricks workspace ([docs](https://docs.databricks.com/en/dev-tools/auth/pat.html))
- Your PAT is used only for the duration of the deploy request — the app never stores or logs it
- Treat your PAT like a password: don't share it, don't paste it into chat or email, and set a short expiration when possible
- If you're not comfortable providing a PAT, use **Log Only** mode and register/deploy from the Databricks UI instead

## Security and Governance

Agent Sweet respects your existing Unity Catalog permissions. Here's how credentials work:

- **Playground** uses your identity (OBO token). You only see data you already have access to.
- **Model registration and endpoint creation** use your Personal Access Token. Models are registered in catalogs you choose, that you have access to, under your identity.
- **MLflow experiment logging** uses the app's service principal, scoped to folders you've explicitly shared. The SP cannot access anything you haven't granted it.
- **Collaboration** is built in. If teammates complete setup, you can load each other's deployed graph definitions, iterate on them, and deploy to your own experiments. The SP's access boundary is the setup grant — nothing more.

The app never creates shadow admin roles, never bypasses UC permissions, and never stores or logs your PAT.

## Local Development

```bash
# Backend
uv run uvicorn backend.main:app --reload --port 8000

# Frontend (proxies /api to :8000)
cd frontend && npm run dev
```

See [CONTRIB.md](CONTRIB.md) for the full developer guide.

## Troubleshooting

| Issue | Fix |
|---|---|
| Setup validation fails | Make sure you created a **folder** (not an MLflow experiment) and granted the SP "Can Manage" |
| Registration fails with auth error | Check that your PAT is valid and you have `CREATE MODEL` on the target catalog/schema |
| Endpoint creation fails | Verify your PAT has `CREATE SERVING ENDPOINT` permissions |
| `requirements-serving.txt` not found | Run `uv pip compile pyproject.toml -o requirements-serving.txt --python-version 3.11` |

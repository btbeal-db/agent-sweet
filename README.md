# Agent Sweet

Visual drag-and-drop [LangGraph](https://langchain-ai.github.io/langgraph/) agent builder for Databricks. Build, preview, and deploy AI agents — no code required.

**Built-in node types:** LLM, Router, Vector Search, Genie, UC Function, MCP Server, Human Input

## Deploy

No infrastructure to provision and no bundle variables to set — the repo's `databricks.yml` handles everything, including the OBO scopes the app needs. Just link the repo:

1. In your Databricks workspace, go to **Compute > Apps**
2. Click **Create App** and give it a name
3. Under **Git repository**, paste this repo's URL
4. Click **Deploy > From Git**, set the branch to `main`, and deploy

The app is live. See [Databricks Apps docs](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/deploy/#deploy-from-a-git-repository) for details.

## First-Time Setup

Each user completes two steps before building agents:

### 1. MLflow experiment folder (one-time, on the Setup page)

This lets the app log MLflow models on your behalf when you deploy.

1. Create a folder under your user directory (e.g. `/Users/you@company.com/agent-sweet`)
2. The Setup page shows the app's service principal name — grant it **Can Manage** on your folder
3. Click **Validate** to confirm

### 2. Confirm the app's OBO scopes

Preview routes data-access requests (Vector Search, Genie, UC Functions, external MCP) through Databricks managed MCP servers, which require specific OBO scopes on your token. The bundle in `databricks.yml` declares them automatically when you deploy via "Deploy from Git", but it's worth verifying — if your workspace has app-authorization policies that strip scopes, or you created the app outside the bundle flow, preview will fail with auth errors that don't obviously point at scopes.

Open your app's **Authorization** page and confirm the user-token scopes include all of:

- `mcp.functions`
- `mcp.vectorsearch`
- `mcp.genie`
- `mcp.external`
- `workspace.workspace`

If any are missing, add them and redeploy. The full mapping of scope → node type is in [How data-access auth works](#how-data-access-auth-works).

## Using the App

### Build

Drag nodes onto the canvas, wire them together, and configure each node. Define your agent's state model in the left panel.

### Preview

Click **Playground** to test your agent with live data. Previews run under your identity using your workspace's on-behalf-of (OBO) credentials — no PAT needed. You only see data you have access to.

### Deploy

Click **Deploy** and choose a deploy mode:

- **Log Only** — saves the agent as an MLflow model in your experiment folder. No PAT required.
- **Log & Register** or **Full Deploy** — requires a PAT for UC registration and serving endpoint creation. Paste it in the deploy modal.

## Security and Governance

Agent Sweet respects your existing Unity Catalog permissions. Here's how credentials work:

- **Preview** uses your workspace identity automatically. All data-access nodes (Vector Search, Genie, UC Functions) route through [Databricks managed MCP servers](https://docs.databricks.com/aws/en/generative-ai/mcp/managed-mcp), which accept the app's on-behalf-of (OBO) token with `mcp.*` scopes. No PAT is needed for building or previewing agents.
- **Deploy** (Log & Register or Full Deploy) requires a PAT for UC model registration and serving endpoint creation, since OBO scopes for these operations are not yet available. Paste it in the deploy modal — it is held in browser memory only and never stored or logged.
- **MLflow experiment logging** uses the app's service principal, scoped to folders you've explicitly shared during setup. The SP cannot access anything you haven't granted it.
- **Collaboration** is built in. If teammates complete setup, you can load each other's deployed graph definitions, iterate on them, and deploy to your own experiments.

### How data-access auth works

All data-access nodes route through Databricks managed MCP servers instead of calling the SDK directly. This is what eliminates the PAT requirement for preview:

| Node | MCP endpoint | OBO scope |
|---|---|---|
| Vector Search | `/api/2.0/mcp/vector-search/{catalog}/{schema}/{index}` | `mcp.vectorsearch` |
| Genie Room | `/api/2.0/mcp/genie/{room_id}` | `mcp.genie` |
| UC Function | `/api/2.0/mcp/functions/{catalog}/{schema}/{function}` | `mcp.functions` |
| MCP Server | User-specified URL | `mcp.external` (for external connections) |

The app declares these scopes in `databricks.yml`. When you log in to the app, your browser's OAuth flow grants a token with these scopes. The app passes this token to the MCP servers, which enforce Unity Catalog permissions — you only see data you have access to.

VS configuration options (reranker, columns, score threshold, query type) are passed via the MCP `_meta` parameter. See the [managed MCP meta parameter docs](https://docs.databricks.com/aws/en/generative-ai/mcp/managed-mcp-meta-param) for details.

### Deployed endpoint permissions

When you deploy an agent, the app declares every external resource your graph references (serving endpoints, Vector Search indexes, Genie rooms, UC functions, and tables) as [MLflow model resources](https://docs.databricks.com/en/machine-learning/manage-model-lifecycle/index.html). At serving time, Model Serving uses **on-behalf-of (OBO) credentials** — each caller's request runs with their own identity and permissions. Your agent doesn't get blanket access to data; each caller only reaches what they're already allowed to see.

The app never creates shadow admin roles, never bypasses UC permissions, and never stores or logs your PAT.

## MCP Server Tools

All data-access nodes (Vector Search, Genie, UC Functions) use [Databricks managed MCP servers](https://docs.databricks.com/aws/en/generative-ai/mcp/managed-mcp) under the hood. You don't need to configure this — the app builds the MCP URL from your node config automatically.

The **MCP Server** node lets you connect to _additional_ MCP servers beyond the built-in node types. Drop an MCP Server onto an LLM node to give the LLM access to all of the server's tools — one URL is all you need.

### Supported server types

| Type | URL pattern | Example |
|---|---|---|
| **Managed MCP** | `<host>/api/2.0/mcp/functions/<catalog>/<schema>` | UC functions, Vector Search indexes, Genie rooms hosted by Databricks |
| **External MCP** | `<host>/api/2.0/mcp/external/<connection>` | Third-party servers (GitHub, Slack, etc.) proxied through a [Unity Catalog connection](https://docs.databricks.com/aws/en/generative-ai/mcp/external-mcp) |
| **Custom MCP** | Any Streamable HTTP URL | Your own MCP servers, including [FastMCP](https://gofastmcp.com/) apps deployed on Databricks Apps |

All three types work for both preview and deploy. Auth is handled automatically using `DatabricksOAuthClientProvider`.

### How it works

1. **Drag** an MCP Server node onto an LLM node (or add it as a standalone graph node)
2. **Paste** the server URL and optionally filter which tools to expose
3. **Preview** — the app discovers available tools from the server and binds them to the LLM
4. **Deploy** — tool metadata (names, descriptions, schemas) is persisted in the model artifact so the served endpoint never needs to re-contact the server for tool discovery

### Configuration

| Field | Required | Description |
|---|---|---|
| **Server URL** | Yes | The MCP server endpoint URL |
| **Tool Filter** | No | Comma-separated list of tool names to expose (empty = all) |
| **Tool Description** | No | Custom description telling the LLM when to use this tool |

When used as a standalone node (not attached to an LLM), you also specify a **Tool Name** to call directly and an **Input from** state variable.

## Conversational Agents and Lakebase

Agents with conversational (multi-turn) LLM nodes need persistent state between requests. Model Serving is stateless, so the app uses [Lakebase](https://docs.databricks.com/aws/en/oltp/) (Databricks-managed PostgreSQL) as a checkpoint store via LangGraph's `PostgresSaver`.

### How it works

At deploy time, the app configures the serving endpoint with Lakebase connection details. At serving time, the model creates a `psycopg` connection pool with a custom connection class that mints a fresh OAuth token on every new connection via `WorkspaceClient().postgres.generate_database_credential()`. Existing connections remain valid after the token expires — Lakebase enforces expiry only at login — so the pool handles rotation transparently.

### Deploy options

When deploying a full endpoint, you have three choices for Lakebase:

| Option | What you provide | What happens |
|---|---|---|
| **Create new** (recommended) | A project ID (e.g. `agent-sweet`) | The app provisions an Autoscaling Lakebase project and creates a per-agent database (e.g. `my-agent-checkpoints`) using your PAT. Multiple agents can share one project. |
| **Use existing** | Endpoint path, host, and database name | The app uses your existing Lakebase instance. Get these values from the Lakebase project page in your workspace. |
| **Connection string** (advanced) | A `postgresql://` URI | Static credential passed as-is. Note: Lakebase OAuth tokens expire after 1 hour, so this is mainly useful for non-Lakebase Postgres instances. |

### Prerequisites

Lakebase requires a workspace with serverless support.

### Default parameters

Auto-provisioned projects use these defaults:

- **Tier:** Autoscaling (0.5–1 CU, scale-to-zero enabled)
- **Branch:** `production` (created automatically)
- **Endpoint:** `primary` read-write (created automatically)
- **Database:** `{catalog}-{schema}-{model}-ckpt` (derived from your full UC model name, e.g. `catalog-schema-my-agent-ckpt`)
- **PostgreSQL version:** Latest supported (currently 16)

These are appropriate for checkpoint storage workloads. For production use with higher throughput, scale the endpoint via the Lakebase project page or CLI.

## Local Development

```bash
# Backend
uv run uvicorn backend.main:app --reload --port 8000

# Frontend (proxies /api to :8000)
cd frontend && npm run dev

# Run tests
uv run pytest -m "not integration" -q
```

CI runs `Frontend Build` and `Backend Tests` on every PR to `dev` and `main`. See [CONTRIB.md](CONTRIB.md) for the full developer guide.

## Troubleshooting

| Issue | Fix |
|---|---|
| Setup validation fails | Make sure you created a **folder** (not an MLflow experiment) and granted the SP "Can Manage" |
| Preview fails with an OBO/auth error after you added scopes | Your browser is still using the OAuth session from before the scopes existed — newly-added scopes are **not** re-requested for an existing session. Clear cookies for the app's hostname (or open it in a private window) and log in again to get a fresh token with the updated scopes. |
| Registration fails with auth error | Check that your PAT is valid and you have `CREATE MODEL` on the target catalog/schema |
| Endpoint creation fails | Verify your PAT has `CREATE SERVING ENDPOINT` permissions |
| `requirements-serving.txt` not found | Run `uv pip compile pyproject.toml -o requirements-serving.txt --python-version 3.11` |

# Agent Builder App

Visual drag-and-drop LangGraph agent builder for Databricks. Users design, test, and deploy AI agents without writing code. Built on LangGraph, MLflow, and Databricks infrastructure (Vector Search, Genie, UC Functions, Lakebase).

## Target User

Data scientists, analysts, and ML practitioners who are comfortable with Databricks but not necessarily writing LangGraph code. They know what a "retrieval agent" or "routing pipeline" is conceptually, but want to wire one up visually rather than hand-coding state graphs. Assume familiarity with concepts like Unity Catalog, serving endpoints, and MLflow runs -- but not with LangGraph internals, OAuth flows, or infrastructure provisioning.

## Stack

- **Frontend**: React 18 + TypeScript, Vite, @xyflow/react (graph canvas), Lucide icons
- **Backend**: FastAPI, Pydantic, LangGraph, MLflow, databricks-sdk, databricks-langchain
- **Deployment**: Databricks Apps (auto-managed compute, OBO token injection)

## User Journey

### 1. Setup (one-time, per user)

User creates a workspace folder (e.g. `/Users/{email}/agent-sweet`), then grants the app's service principal "Can Manage" on that folder. The app validates by creating a test MLflow experiment and persists a `.agent-builder-setup.json` config file in the folder.

- `GET /api/setup/status` -- checks if setup is complete (reads config from workspace file)
- `GET /api/setup/info` -- returns SP display name + user email (for the setup wizard UI)
- `POST /api/setup/validate` -- validates folder access, creates experiment, persists config

### 2. Build

Drag nodes onto the canvas, connect them, define a state model. Available node types:

- **LLM** -- ChatDatabricks, system prompt, structured output, conversational mode, tool calling
- **Router** -- conditional branching on a state field (keyword match, boolean, fallback)
- **Vector Search** -- query a VS index with optional reranking and filters
- **Genie** -- query a Databricks Genie room, formats SQL results as text
- **UC Function** -- call a Unity Catalog function with JSON parameters
- **MCP Server** -- connect to an MCP server and expose its tools to LLM nodes
- **Human Input** -- pause the graph, prompt the user, resume with their answer

State model: user-defined fields (`str`, `int`, `float`, `bool`, `list[str]`, `structured`). The `messages` field uses LangGraph's `add_messages` reducer for multi-turn history.

### 3. Preview / Playground

`POST /api/graph/preview` compiles the GraphDef into a LangGraph StateGraph and runs it with in-memory checkpointing. Returns output, full execution trace, state snapshot, and MLflow spans. Supports multi-turn (thread_id) and human-in-the-loop (resume_value).

### 4. Deploy

`POST /api/graph/deploy` -- streamed SSE with steps: validate, provision Lakebase (if conversational), log model, register in UC, create serving endpoint.

Three modes:
- **Log Only** -- no PAT required, registers later via UI
- **Log & Register** -- requires PAT, registers model in UC
- **Full Deploy** -- requires PAT, registers + creates serving endpoint

## Authentication Model

Three credential types. The PAT-first model is a pragmatic response to platform limitations, not a design preference -- if OBO scopes for Vector Search, Unity Catalog writes, and MLflow become available, the PAT requirement can be removed. The OBO fallback path is already wired in via `get_data_client()`.

### Why PAT instead of OBO?

Databricks Apps inject an OBO token per request, but many critical scopes don't work (as of April 2026):

- `vector-search` -- required by the VS API, but **not a valid configurable OBO scope** (the platform rejects it)
- `unity-catalog` -- scope exists but returns 403 for `tables.get` and write operations
- `model-serving` (write) -- appears in OAuth discovery but doesn't grant access
- `mlflow` / `ml.experiments` -- does not exist as an OBO scope

We verified this with a bare-bones diagnostic endpoint (`GET /api/test-vs` in `main.py`) that tries every auth combination. The endpoint is kept for future regression testing. No custom `user_api_scopes` are declared in `databricks.yml` -- the default scopes (`iam.current-user:read`, `iam.access-control:read`) are sufficient.

### Deployment is zero-config

Users link the GitHub repo to a Databricks App and deploy. No custom scopes, no bundle variables, no infrastructure to provision. The only prerequisites are:

1. **MLflow setup (one-time)** -- user creates a workspace folder and grants the SP "Can Manage" so the app can log models during deploy
2. **PAT (each session)** -- user pastes a PAT in the builder banner so the app can access their workspace resources

### Credential types

**User PAT** -- provided via the builder banner UI. Stored in React `useState` (browser memory only, never persisted). Sent with preview/deploy requests. Backend holds it in a `ContextVar`, cleared in `finally` after each request.

- `get_data_client()` in `auth.py`: returns a PAT client if available, OBO fallback otherwise
- All data-access nodes (VS, Genie) and tools call `get_data_client()`
- Deploy modal pre-fills from the banner PAT

**OBO Token** -- injected by Apps proxy via `x-forwarded-access-token`. Stored per-request in a `ContextVar` by `OBOMiddleware`.

- `get_workspace_client()` in `auth.py`: masks SP env vars + `auth_type="pat"` (both required -- without masking, the SDK loads SP creds into its Config and the server treats it as an SP OAuth call)
- Used for: user identity (`current_user.me()`), and as the fallback in `get_data_client()` when no PAT is provided

**Service Principal (SP)** -- env vars auto-injected by the Apps platform. `get_sp_workspace_client()` in `auth.py`.

- Used for: LLM calls (FMAPI rejects OBO/PAT), MLflow experiment logging (no OBO scope), setup config persistence
- SP access is scoped: it can only reach folders users have explicitly granted during setup

**Implementation detail**: `mlflow.register_model()` runs in a subprocess because MLflow caches `DatabricksConfig` via `@lru_cache` -- env-var masking in the same process doesn't override it.

| Operation | Credential | Why |
|---|---|---|
| Preview -- VS, Genie, UC Functions | PAT > OBO | PAT preferred; OBO lacks `vector-search` scope |
| Preview -- MCP (managed URLs) | PAT > OBO | Same as VS/Genie; managed MCP is a workspace API |
| Preview -- MCP (Databricks Apps) | OBO > PAT | Apps URLs prefer OBO (OAuth); PAT is fallback |
| Preview -- LLM inference | SP | FMAPI rejects OBO and PAT |
| User identity | OBO | Default `iam.current-user:read` scope works |
| MLflow experiment logging | SP | No OBO scope for MLflow |
| Setup config persistence | SP | Workspace file write (SP has Can Manage) |
| UC model registration | PAT | No UC write OBO scopes |
| Serving endpoint creation | PAT | `model-serving` OBO scope unreliable |

## MCP Server Node

Connects to MCP servers and exposes their tools to LLM nodes. One URL auto-discovers all available tools — unlike UC Function nodes where each function is configured individually.

### Supported MCP URL types

- **Managed MCP** (`<host>/api/2.0/mcp/functions/<catalog>/<schema>`, `.../vector-search/...`, `.../genie/...`) -- Databricks-hosted, PAT works directly.
- **Custom MCP on Databricks Apps** (`*.databricksapps.com/mcp`) -- user-deployed FastMCP servers. On the deployed app, auth flows through automatically via the OBO token.
- **External MCP** (`<host>/api/2.0/mcp/external/<connection>`) -- UC connection proxy to external servers. Requires connection setup in Unity Catalog (not yet wired into the node config).

### Implementation notes

- Bypasses `DatabricksMCPClient` from `databricks_mcp` for the data path. That SDK rejects PAT auth for Apps URLs (client-side validation), but PAT/OBO tokens work fine at the HTTP level. We use the raw MCP SDK (`streamablehttp_client` + `ClientSession`) directly.
- All MCP calls run in `_run_mcp_in_thread()` because the MCP SDK uses `asyncio.run()` internally, which crashes inside FastAPI's event loop.
- `_get_mcp_token(server_url)` selects the right credential: OBO first for Apps URLs, then the standard PAT > OBO > SP chain via `get_data_client()`.
- Deploy-time resource extraction (`_extract_resources` in `main.py`) still uses `DatabricksMCPClient.get_databricks_resources()` with SP credentials, since that runs in a thread pool and needs programmatic resource resolution.

## Known Gotchas

- **MLflow artifact downloads from Apps**: `mlflow.artifacts.download_artifacts()` follows presigned URL redirects to `storage.cloud.databricks.com`, which is unreachable from Databricks Apps networking. DBFS root is also disabled. We removed the run-ID-based loading feature in favor of direct JSON paste/import.
- **Lakebase OAuth token expiry**: Autoscaling projects use tokens that expire after 1 hour. Serving endpoints use a `ConnectionPool` with a custom `Connection` subclass that calls `generate_database_credential()` for fresh tokens on each new connection.
- **CPU serving tracing**: Endpoints need `ENABLE_MLFLOW_TRACING=true` and `MLFLOW_EXPERIMENT_ID` env vars explicitly. `autolog()` alone is insufficient.
- **OBO + SP env var conflict**: The SDK loads `client_id`/`client_secret` from env into its Config even with `auth_type="pat"`. If both are present, the server treats it as an SP OAuth call (wrong scopes). `get_workspace_client()` masks SP env vars before creating an OBO client AND passes `auth_type="pat"`. Both are required. Always restore via `finally`.

## Dev Preferences

- Prefer existing dependencies over new ones when the SDK already covers the functionality.
- Don't add migration/compatibility layers for loading older graph JSON -- keep it simple, let the user fix stale field names manually.
- Keep deploy flow using SP credentials until OBO scopes for MLflow/UC actually work.

## Project Structure

```
backend/
  main.py          -- FastAPI app, routes, deploy flow, middleware
  auth.py          -- OBO/SP/PAT token handling, WorkspaceClient factories
  schema.py        -- Pydantic models (GraphDef, NodeDef, etc.)
  graph_builder.py -- Compiles GraphDef -> LangGraph StateGraph, runs it
  mlflow_model.py  -- MLflow ResponsesAgent wrapper (entry point for serving)
  lakebase.py      -- Lakebase provisioning + Postgres connection pool
  setup.py         -- Setup endpoints
  tools.py         -- Tool factories (VS, Genie, UC Function, MCP)
  nodes/           -- Pluggable node types (auto-discovered via pkgutil)
    base.py        -- BaseNode ABC, NodeConfigField, resolve_state()
    llm_node.py, router_node.py, vector_search_node.py, mcp_node.py, etc.

frontend/src/
  App.tsx           -- Main shell, view routing, state management
  api.ts            -- Backend API client
  types.ts          -- TypeScript interfaces
  components/
    Canvas.tsx      -- @xyflow graph editor
    ConfigPanel.tsx -- Node config form (auto-renders by field_type)
    DeployModal.tsx -- Deploy wizard
    SetupPage.tsx   -- Setup wizard
    ChatPlayground.tsx -- Preview/test agent

app.yaml           -- Databricks Apps runtime config
databricks.yml     -- Asset Bundle definition (app name + uvicorn command, no custom scopes)
deploy.sh          -- Build frontend + bundle deploy + app deploy
```

## Adding a New Node Type

1. Create `backend/nodes/your_node.py` with a class extending `BaseNode`, decorated with `@register`
2. Implement `node_type`, `display_name`, `config_fields`, and `execute(state, config)`
3. If it accesses Databricks resources: use `get_data_client()` (PAT > OBO) and add resource extraction in `main.py:_extract_resources()`
4. If it can be an LLM tool: set `tool_compatible = True` and add a factory in `tools.py`

# AgentSweet

Visual drag-and-drop LangGraph agent builder for Databricks. Users design, test, and deploy AI agents without writing code. Built on LangGraph, MLflow, and Databricks infrastructure (Vector Search, Genie, UC Functions, Lakebase).

## Target User

Data scientists, analysts, and ML practitioners who are comfortable with Databricks but not necessarily writing LangGraph code. They know what a "retrieval agent" or "routing pipeline" is conceptually, but want to wire one up visually rather than hand-coding state graphs. Assume familiarity with concepts like Unity Catalog, serving endpoints, and MLflow runs -- but not with LangGraph internals, OAuth flows, or infrastructure provisioning.

## Stack

- **Frontend**: React 18 + TypeScript, Vite, @xyflow/react (graph canvas), Lucide icons
- **Backend**: FastAPI, Pydantic, LangGraph, MLflow, databricks-sdk, databricks-langchain
- **Deployment**: Databricks Apps (auto-managed compute, OBO token injection)

## User Journey

### 1. Setup (one-time, per user)

User creates a workspace folder (e.g. `/Users/{email}/agent-sweet`), then grants the app's service principal "Can Manage" on that folder. The app validates by creating a test MLflow experiment and persists a `.agent-sweet-setup.json` config file in the folder.

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

Three credential types. All data-access operations (VS, Genie, UC Functions) are routed through Databricks managed MCP servers, which accept OBO tokens with `mcp.*` scopes. This eliminates the PAT requirement for preview. PATs are still needed for deploy operations (UC model registration, serving endpoint creation) where no OBO scopes exist.

### Managed MCP routing (OBO, no PAT)

Data-access nodes (Vector Search, Genie, UC Functions) have two execution paths controlled by `is_serving()` in `auth.py`:

- **App preview** (`is_serving()=False`): routes through managed MCP endpoints. The Apps OBO token only has `mcp.*` scopes (`mcp.vectorsearch`, `mcp.genie`, `mcp.functions`, `mcp.external`), declared in `databricks.yml`.
- **Serving** (`is_serving()=True`): uses the Databricks SDK directly. Serving credentials (user OBO or SP) work with the SDK — no MCP overhead.

`is_serving()` is set once by `mlflow_model.py` at model load time. Tool factories and node `execute()` methods branch on it (e.g. `_make_vector_search_tool_sdk` vs `_make_vector_search_tool_mcp`). If direct SDK OBO scopes become available for Apps, the MCP path can be removed.

### Deployment prerequisites

Users link the GitHub repo to a Databricks App and deploy. The only prerequisites are:

1. **MLflow setup (one-time)** -- user creates a workspace folder and grants the SP "Can Manage" so the app can log models during deploy
2. **PAT (deploy only)** -- needed for UC model registration and serving endpoint creation (no OBO scopes for these)

### Credential types

**OBO Token** -- injected by Apps proxy via `x-forwarded-access-token`. Stored per-request in a `ContextVar` by `OBOMiddleware`.

- Primary credential for all data access in preview (via managed MCP)
- `get_workspace_client()` in `auth.py`: masks SP env vars + `auth_type="pat"` (both required -- without masking, the SDK loads SP creds into its Config and the server treats it as an SP OAuth call)
- Used for: user identity, VS/Genie/UC queries (through MCP), MCP tool discovery

**User PAT** -- optionally provided for deploy operations. Stored in React `useState` (browser memory only, never persisted). Backend holds it in a `ContextVar`, cleared in `finally` after each request.

- `get_data_client()` in `auth.py`: returns a PAT client if available, OBO fallback otherwise
- Used for: UC model registration, serving endpoint creation

**Service Principal (SP)** -- env vars auto-injected by the Apps platform. `get_sp_workspace_client()` in `auth.py`.

- Used for: LLM calls (FMAPI rejects OBO/PAT), MLflow experiment logging (no OBO scope), setup config persistence
- SP access is scoped: it can only reach folders users have explicitly granted during setup

**Implementation detail**: `mlflow.register_model()` runs in a subprocess because MLflow caches `DatabricksConfig` via `@lru_cache` -- env-var masking in the same process doesn't override it.

| Operation | Credential | Why |
|---|---|---|
| Preview -- VS, Genie, UC Functions | OBO (via managed MCP) | `mcp.*` scopes in `databricks.yml` |
| Preview -- MCP Server nodes | OBO > PAT | `DatabricksOAuthClientProvider`; managed MCP URLs prefer OBO |
| Preview -- LLM inference | SP | FMAPI rejects OBO and PAT |
| User identity | OBO | Default `iam.current-user:read` scope works |
| MLflow experiment logging | SP | No OBO scope for MLflow |
| Setup config persistence | SP | Workspace file write (SP has Can Manage) |
| UC model registration | PAT | No UC write OBO scopes |
| Serving endpoint creation | PAT | `model-serving` OBO scope unreliable |

## Managed MCP Integration

All data-access nodes (VS, Genie, UC Functions) and the MCP Server node route through Databricks managed MCP servers. This is the core mechanism that enables OBO auth without PATs for preview.

### How it works

Each node type builds a managed MCP URL from its config:
- **Vector Search**: `index_name` → `/api/2.0/mcp/vector-search/{catalog}/{schema}/{index}`
- **Genie**: `room_id` → `/api/2.0/mcp/genie/{room_id}`
- **UC Function**: `function_name` → `/api/2.0/mcp/functions/{catalog}/{schema}/{function}`

URL builders in `tools.py`: `_vs_mcp_url()`, `_genie_mcp_url()`, `_uc_function_mcp_url()`.

For standalone node execution, `_mcp_discover_and_call()` combines tool discovery and invocation in a single MCP session to minimize round-trips.

### MCP Server Node

The MCP Server node supports all URL types directly:

- **Managed MCP** (`<host>/api/2.0/mcp/functions/<catalog>/<schema>`, `.../vector-search/...`, `.../genie/...`) -- Databricks-hosted managed MCP servers for UC functions, Vector Search, and Genie.
- **External MCP** (`<host>/api/2.0/mcp/external/<connection>`) -- UC connection proxy to external servers (e.g. GitHub, Slack). Requires a Unity Catalog connection to be configured in the workspace.
- **Custom MCP on Databricks Apps** (`*.databricksapps.com/mcp`) -- user-deployed FastMCP servers on Databricks Apps.

### Authentication

All MCP communication uses `DatabricksOAuthClientProvider` from `databricks_mcp` for proper OAuth auth. This is required by the Databricks MCP proxy — raw Bearer token headers do not work for external MCP connections.

- `_get_mcp_client(server_url)` in `tools.py` returns a `WorkspaceClient` with the right credentials: OBO first for managed MCP URLs and Databricks Apps URLs, then `get_data_client()` (PAT > OBO > SP) for everything else.
- `_mcp_session(server_url, client)` wraps the MCP SDK's `streamablehttp_client` with `auth=DatabricksOAuthClientProvider(client)`.
- Each tool **call** gets a fresh `WorkspaceClient` via `_get_mcp_client()` so tokens are never stale.

### Tool discovery and persistence

MCP tool metadata (names, descriptions, input schemas) can be resolved two ways:

- **Live discovery** (preview): connects to the MCP server at execution time via `_mcp_list_tools()`. Retries once for cold-start on Databricks Apps.
- **Persisted metadata** (deployed models): at deploy time, `_persist_mcp_tool_metadata()` in `main.py` discovers tools for **all** MCP-routed types (`mcp_server`, `vector_search`, `genie`, `uc_function`) and injects `discovered_tools` into the graph_def artifact. The served model builds LangChain tools from this metadata without ever contacting the MCP server for discovery. Only actual tool **calls** hit the server at inference time.

This split exists because serving endpoints may not be able to reach MCP servers for discovery (network/auth differences), but they can reach them for individual tool calls with proper resource declarations.

If `discovered_tools` is present in the config, `_make_mcp_tools()` uses it. Otherwise it falls back to live discovery. The `discover_mcp_tool_metadata()` helper returns serializable dicts suitable for JSON persistence. `managed_mcp_url_for_tool()` converts VS/Genie/UC configs into managed MCP URLs for persistence.

### MCP `_meta` parameters

The MCP spec's `_meta` field carries preset configuration alongside the LLM-generated `arguments`. Supported by managed MCP servers:

**Vector Search** -- `num_results`, `columns`, `columns_to_rerank`, `filters`, `include_score`, `score_threshold`, `query_type` (ANN/HYBRID). These map directly from the VS node's config fields. Built by `_build_vs_meta()` in `tools.py`.

**UC Functions** -- No `_meta` params. Arguments are passed as kwargs by parameter name in the `arguments` dict (e.g. `{"number_1": 36939.0, "number_2": 8922.4}`). Tool names use `__` separator (e.g. `CATALOG__SCHEMA__function_name`).

**Genie** -- No `_meta` params documented. The MCP server handles query polling internally.

### Implementation notes

- All MCP calls run in `_run_mcp_in_thread()` because the MCP SDK uses `asyncio.run()` internally, which crashes inside FastAPI's event loop.
- Tool creation uses `StructuredTool` with the MCP tool's `inputSchema` dict as `args_schema`. LangChain 1.2+ accepts raw JSON Schema dicts here.
- Deploy-time resource extraction (`_extract_resources` in `main.py`) still uses `DatabricksMCPClient.get_databricks_resources()` with SP credentials, since that runs in a thread pool and needs programmatic resource resolution.
- Standalone node execution uses `_mcp_discover_and_call()` which combines discovery + invocation in a single session to reduce overhead.
- MCP URL note: docs specify three-part URLs for VS and UC (`catalog/schema/resource`), but the `databricks_mcp` SDK regex only matches two-part (`catalog/schema`). Both may work — the SDK regex is for resource classification only, not request routing.

## Known Gotchas

- **MLflow artifact downloads from Apps**: `mlflow.artifacts.download_artifacts()` follows presigned URL redirects to `storage.cloud.databricks.com`, which is unreachable from Databricks Apps networking. DBFS root is also disabled. We removed the run-ID-based loading feature in favor of direct JSON paste/import.
- **Lakebase OAuth token expiry**: Autoscaling projects use tokens that expire after 1 hour. Serving endpoints use a `ConnectionPool` with a custom `Connection` subclass that calls `generate_database_credential()` for fresh tokens on each new connection.
- **CPU serving tracing**: Endpoints need `ENABLE_MLFLOW_TRACING=true` and `MLFLOW_EXPERIMENT_ID` env vars explicitly. `autolog()` alone is insufficient.
- **OBO + SP env var conflict**: The SDK loads `client_id`/`client_secret` from env into its Config even with `auth_type="pat"`. If both are present, the server treats it as an SP OAuth call (wrong scopes). `get_workspace_client()` masks SP env vars before creating an OBO client AND passes `auth_type="pat"`. Both are required. Always restore via `finally`.
- **Streaming duplication in predict_stream**: LangGraph's `stream_mode="messages"` yields both `AIMessageChunk` (incremental tokens) and `AIMessage` (the final complete message). Since `AIMessageChunk` is a subclass of `AIMessage`, `isinstance(msg, AIMessage)` matches both — causing the full text to be emitted twice. Use `type(msg) is AIMessageChunk` to filter only incremental chunks. The `response.completed` SSE event must also be omitted because the Databricks AI Playground renders its output array as additional text.

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

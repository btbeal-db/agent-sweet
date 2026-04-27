---
name: integration-testing
description: Test agent graph changes against a deployed AgentSweet app. Use when verifying preview, deploy, or MCP tool behavior via the app's REST API. Triggers on "test the app", "integration test", "try this graph", "preview this", "deploy this model".
---

# Integration Testing via App API

Test agent graph changes by calling the deployed AgentSweet app's REST API directly. The app is deployed from a git branch — push your changes, wait for the app to pick them up, then hit the API.

## Prerequisites

Before testing, you need:

1. **App URL** — ask the user which app instance to target (e.g. `https://<host>/apps/agent-sweet-dev`)
2. **Git branch** — confirm which branch the app is deployed from (e.g. `dev`, `main`, or a feature branch)
3. **PAT** — obtain from the user's Databricks CLI. Ask which profile to use, then run:
   ```bash
   databricks auth token --profile <PROFILE> | jq -r '.access_token'
   ```
   If the token is expired, ask the user to re-authenticate:
   ```bash
   ! databricks auth login --profile <PROFILE>
   ```
   Never log or persist the token beyond the current request.

## API Endpoints

All endpoints are relative to the app URL (e.g. `https://<host>/apps/agent-sweet-dev/api/...`).

### List available node types

```bash
curl -s "$APP_URL/api/nodes" | jq
```

Returns metadata for every registered node type (LLM, Router, Vector Search, Genie, UC Function, MCP Server, Human Input) including their `config_fields`.

### Preview a graph

`POST /api/graph/preview` — compiles and runs the graph in-memory. This is the fastest way to test changes.

```bash
curl -s -X POST "$APP_URL/api/graph/preview" \
  -H "Content-Type: application/json" \
  -d '{
    "graph": { ...GraphDef JSON... },
    "input_message": "Hello, what can you help me with?",
    "pat": "dapi..."
  }'
```

**Request body** (`PreviewRequest`):

| Field | Required | Description |
|-------|----------|-------------|
| `graph` | Yes | Full `GraphDef` JSON (nodes, edges, state_fields) |
| `input_message` | Yes | The user message to send |
| `thread_id` | No | Reuse for multi-turn conversations |
| `resume_value` | No | Resume from a human-in-the-loop interrupt |
| `pat` | No | PAT for data-access nodes (VS, Genie, MCP, UC Functions) |

**Response** (`PreviewResponse`):

| Field | Description |
|-------|-------------|
| `success` | Whether the graph executed without error |
| `output` | The agent's text output |
| `error` | Error message if `success` is false |
| `execution_trace` | Message history from this turn |
| `state` | Full state snapshot after execution |
| `thread_id` | Thread ID for follow-up turns |
| `interrupt` | Human-in-the-loop prompt if the graph paused |
| `mlflow_trace` | MLflow span data for debugging |

### Deploy a model

`POST /api/graph/deploy` — logs the graph as an MLflow model. Streams SSE events for progress.

**IMPORTANT — experiment_path composition.** The setup wizard stores a
workspace *folder* (e.g. `/Users/you@company.com/agent-sweet`). You cannot
deploy to that folder directly: a Databricks workspace path is either a folder
or an experiment, never both. You must pass a *sub-path* inside that folder as
`experiment_path`. The UI enforces this by prepending the setup folder and
only letting the user type the suffix. When calling the API directly, do the
same:

```
experiment_path = "{setup_folder}/{unique_experiment_name}"
# e.g. "/Users/you@company.com/agent-sweet/ci_weather_agent"
```

Use a name unique per test (model name slug, git SHA, timestamp, etc.) so
runs don't collide. If you pass just the setup folder, the deploy returns a
clear error pointing at the fix.

```bash
curl -s -X POST "$APP_URL/api/graph/deploy" \
  -H "Content-Type: application/json" \
  -d '{
    "graph": { ...GraphDef JSON... },
    "experiment_path": "/Users/you@company.com/agent-sweet/ci_weather_agent",
    "deploy_mode": "log_only",
    "auth_mode": "obo",
    "pat": "dapi..."
  }'
```

**Deploy modes** (`deploy_mode`):

| Mode | PAT required | What it does |
|------|-------------|--------------|
| `log_only` | No | Logs model to MLflow experiment. No UC registration. |
| `log_and_register` | Yes | Logs + registers model in Unity Catalog (`model_name` required) |
| `full` | Yes | Logs + registers + creates a serving endpoint |

**Auth modes** (`auth_mode`):

| Mode | Description |
|------|-------------|
| `obo` | On-behalf-of — callers use their own identity at serving time |
| `passthrough` | System SP — the endpoint's SP handles all auth |

**Additional deploy fields**:

| Field | Description |
|-------|-------------|
| `model_name` | UC path: `catalog.schema.model_name` (required for register/full) |
| `experiment_path` | MLflow experiment path — must be a *sub-path inside* the setup folder, not the folder itself (required) |
| `lakebase_project_id` | Auto-provision Lakebase for multi-turn (e.g. `"my-team"`) |
| `lakebase_existing_project_id` | Use an existing Lakebase project |

The response is an SSE stream of `DeployEvent` objects with `step`, `status` (`running`/`done`/`error`/`skipped`), and `message`.

## Using Example Graphs

The `examples/` directory contains ready-to-use graph JSON files. The user may point you to one of these, or supply their own `.json` file. Always check there first before building a graph from scratch.

| File | Description |
|------|-------------|
| `examples/email_draft_agent.json` | Multi-node email drafting pipeline |
| `examples/joke_rewriter_agent.json` | LLM chain with router and structured output |
| `examples/mcp_tool_calling_agent.json` | LLM with MCP tools attached |
| `examples/medical_assistant_agent.json` | RAG-style agent with Vector Search |

To use an example, read the file and pass its contents as the `graph` field in the preview or deploy request.

## Building a GraphDef

A `GraphDef` has four parts: `nodes`, `edges`, `state_fields`, and optionally `output_fields`.

### Minimal example: START -> LLM -> END

```json
{
  "nodes": [
    {
      "id": "llm_1",
      "type": "llm",
      "writes_to": "output",
      "config": {
        "endpoint": "databricks-meta-llama-3-3-70b-instruct",
        "system_prompt": "You are a helpful assistant.",
        "temperature": 0.7
      }
    }
  ],
  "edges": [
    {"id": "e1", "source": "__start__", "target": "llm_1"},
    {"id": "e2", "source": "llm_1", "target": "__end__"}
  ],
  "state_fields": [
    {"name": "input", "type": "str", "description": "User input"},
    {"name": "output", "type": "str", "description": "LLM response"}
  ]
}
```

### LLM with MCP tools attached

Attach tools via `tools_json` in the LLM node's config:

```json
{
  "id": "llm_1",
  "type": "llm",
  "writes_to": "output",
  "config": {
    "endpoint": "databricks-meta-llama-3-3-70b-instruct",
    "system_prompt": "You are a helpful assistant with access to tools.",
    "temperature": 0.7,
    "include_message_history": "true",
    "tools_json": "[{\"type\": \"mcp_server\", \"config\": {\"server_url\": \"https://<host>/api/2.0/mcp/functions/catalog/schema\"}}]"
  }
}
```

### Node types and key config fields

| Type | Key config fields |
|------|------------------|
| `llm` | `endpoint`, `system_prompt`, `temperature`, `tools_json`, `include_message_history` |
| `router` | `evaluates` (state field), `routes_json` (array of `{label, match_value}`) |
| `vector_search` | `index_name`, `endpoint_name`, `columns`, `num_results`, `query_from` |
| `genie` | `room_id`, `query_from` |
| `uc_function` | `function_name`, `query_from` |
| `mcp_server` | `server_url`, `tool_filter`, `tool_name` (standalone only), `query_from` |
| `human_input` | `prompt_template` |

### Graph structure rules

- Every graph must have edges from `__start__` and to `__end__`
- Each node's `writes_to` must match a field in `state_fields`
- `tools_json` is a JSON **string** (escaped JSON inside the config object)
- Router edges use `source_handle` to match route labels

## Testing Workflow

1. **Push your branch** and confirm the app has picked up the new code
2. **Build a graph JSON** that exercises the feature you changed
3. **Preview first** — call `/api/graph/preview` to verify the graph executes correctly
4. **Check the response** — look at `output`, `execution_trace`, and `mlflow_trace`
5. **Deploy with `log_only`** — call `/api/graph/deploy` to verify the model logging flow (auth, resource extraction, artifact persistence) without needing UC registration
6. **Escalate if needed** — use `log_and_register` or `full` to test the full deploy pipeline
7. **Multi-turn** — reuse the `thread_id` from the preview response for follow-up messages

## Full Serving Endpoint Test

When you need to validate the complete path — model logging, UC registration, endpoint creation, inference, and tracing — use a `full` deploy and then invoke the served endpoint.

### 1. Deploy with `full` mode

```bash
curl -s -X POST "$APP_URL/api/graph/deploy" \
  -H "Content-Type: application/json" \
  -d '{
    "graph": { ...GraphDef JSON... },
    "model_name": "catalog.schema.my_test_agent",
    "experiment_path": "/Users/you@company.com/agent-sweet/my_test_agent",
    "deploy_mode": "full",
    "auth_mode": "obo",
    "pat": "'"$TOKEN"'"
  }'
```

Parse the SSE stream for the `endpoint_name` in the final event's `data` field.

### 2. Poll for endpoint readiness

The serving endpoint takes a few minutes to provision. Poll until the state is `READY`:

```bash
databricks serving-endpoints get <endpoint-name> --profile <PROFILE> -o json | jq '.state'
```

Or poll in a loop:

```bash
while true; do
  STATE=$(databricks serving-endpoints get <endpoint-name> --profile <PROFILE> -o json | jq -r '.state.ready')
  echo "State: $STATE"
  [ "$STATE" = "READY" ] && break
  sleep 15
done
```

### 3. Invoke the served endpoint

Once ready, call the endpoint using the Responses API format:

```bash
curl -s -X POST "https://<workspace-host>/serving-endpoints/<endpoint-name>/invocations" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "input": [{"role": "user", "content": [{"type": "input_text", "text": "Hello, what can you do?"}]}]
  }'
```

### 4. Retrieve the trace

After invocation, find the trace in the MLflow experiment. Use the experiment path from the deploy request:

```bash
# Get the experiment ID
EXP_ID=$(databricks experiments get-by-name --experiment_name "/Users/you@company.com/agent-sweet" --profile <PROFILE> -o json | jq -r '.experiment.experiment_id')

# List recent traces
databricks api get /api/2.0/mlflow/traces?experiment_id=$EXP_ID --profile <PROFILE> | jq '.traces[0]'
```

Or use the trace ID directly if it was returned in the response headers. Read the trace to verify:

- The LLM received the correct tools (check the tool definitions in the LLM span inputs)
- Tool calls executed successfully (check tool span outputs)
- No unexpected errors in any span
- Streaming produced the right content (compare span output to endpoint response)

## What to Test

This is a general-purpose integration testing workflow. Use it whenever you change something that could affect the end-to-end path from graph definition to deployed model:

- **Auth changes** — verify preview and deploy still work with the right credentials
- **New or modified node types** — build a graph using the node and confirm it executes
- **MLflow model changes** (`mlflow_model.py`) — deploy with `log_only` and verify the artifact is correct
- **Tool wiring changes** (`tools.py`, `llm_node.py`) — preview a graph with attached tools and check the LLM calls them
- **Streaming changes** — deploy and call the served endpoint to verify no duplication or missing content
- **Resource extraction changes** — deploy and verify the SSE events report the right resources

## Examples

### Example: Verify a node change end-to-end
User says: "Test that our LLM node changes didn't break anything"

1. Get the app URL and Databricks CLI profile from the user
2. Obtain a token via `databricks auth token --profile <PROFILE>`
3. Build a simple START -> LLM -> END graph
4. Preview it against the app — confirm `success: true` and a reasonable `output`
5. Deploy with `log_only` — confirm the SSE stream completes without errors

### Example: Verify deploy flow after auth changes
User says: "Make sure deploy still works after the auth refactor"

1. Build a graph that uses data-access nodes (VS, Genie, MCP, or UC Function)
2. Preview with a PAT — verify the nodes can reach the resources
3. Deploy with `log_only` — verify resource extraction and model logging succeed
4. Check the SSE events for `"status": "done"` on each step

### Example: Test multi-turn conversation
User says: "Test that multi-turn still works in preview"

1. Send a first message and capture the returned `thread_id`
2. Send a follow-up message with the same `thread_id`
3. Verify the response shows awareness of the prior turn

### Example: Full serving endpoint validation
User says: "Deploy this to a serving endpoint and make sure it works end-to-end"

1. Get app URL, CLI profile, experiment path, and UC model name from the user
2. Obtain a token via `databricks auth token --profile <PROFILE>`
3. Build the graph JSON for the feature being tested
4. Deploy with `full` mode — parse the SSE stream for the endpoint name
5. Poll `databricks serving-endpoints get <name>` until state is `READY`
6. Invoke the endpoint with a test message
7. Retrieve the trace from the MLflow experiment
8. Inspect the trace spans for correct tool binding, successful execution, and expected output

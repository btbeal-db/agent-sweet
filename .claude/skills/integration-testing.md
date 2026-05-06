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
3. **Token** — either a PAT or an OAuth U2M token from the user's Databricks CLI:
   ```bash
   databricks auth token --profile <PROFILE> | jq -r '.access_token'
   ```
   OAuth U2M tokens work in the `pat` field of `/api/graph/deploy` — the SDK accepts them as bearer tokens for UC writes and serving-endpoint creation. If auth fails, ask the user to re-authenticate:
   ```bash
   ! databricks auth login --profile <PROFILE>
   ```
   Never log or persist the token beyond the current request.

## Sync the app to your branch first

If you've just pushed commits, the deployed app may still be on an older commit. Compare and redeploy without waiting:

```bash
CURRENT=$(databricks --profile <PROFILE> apps get <APP_NAME> | jq -r '.active_deployment.git_source.resolved_commit')
LATEST=$(git rev-parse HEAD)
if [ "$CURRENT" != "$LATEST" ]; then
  databricks --profile <PROFILE> apps deploy <APP_NAME> \
    --json '{"git_source":{"branch":"<BRANCH>"},"mode":"SNAPSHOT"}' --no-wait
  # Poll until the active deployment matches LATEST (~30-60s for code-only changes)
  until s=$(databricks --profile <PROFILE> apps get <APP_NAME> | jq -r '.active_deployment.git_source.resolved_commit'); [[ "$s" == "$LATEST" ]]; do sleep 8; done
fi
```

Only the **branch** is set in the deploy JSON — `git_repository.url` must already be configured at the app level.

## API Endpoints

All endpoints are relative to the app URL (e.g. `https://<host>/apps/agent-sweet-dev/api/...`).

### List available node types

```bash
curl -s "$APP_URL/api/nodes" | jq
```

Returns metadata for every registered node type (LLM, Router, Vector Search, Genie, UC Function, MCP Server, Human Input) including their `config_fields`.

### Preview a graph

`POST /api/graph/preview` — compiles and runs the graph in-memory, mirroring the deployed agent's `predict_stream`. The response is an **SSE stream** of token-level deltas plus a single terminal event. Use `-N` with `curl` so it doesn't buffer.

```bash
curl -sN -X POST "$APP_URL/api/graph/preview" \
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

**Response** — `Content-Type: text/event-stream`. Each line of interest looks like `data: {...}\n\n`. Event shapes:

| `type` | Payload | When |
|--------|---------|------|
| `delta` | `{text}` | Per LLM token. Concatenate to build the streamed reply. |
| `done` | `{thread_id, output, execution_trace, state, mlflow_trace}` | Graph completed. Terminal. |
| `interrupt` | `{thread_id, prompt, execution_trace, state, mlflow_trace}` | Graph paused at a HumanInput node. Terminal — resume by re-posting with the same `thread_id` and `resume_value`. |
| `error` | `{message}` | Execution failed. Terminal. |

To test from a script, drain the stream and look at the terminal event:

```bash
# Capture the full SSE stream and pull out the last data: line
TERMINAL=$(curl -sN -X POST "$APP_URL/api/graph/preview" \
  -H "Content-Type: application/json" \
  -d '{...}' \
  | grep '^data: ' | tail -1 | cut -c7-)
echo "$TERMINAL" | jq '.type, .output'
```

For multi-turn or resume flows, parse `thread_id` out of the terminal event and pass it back on the next request. When the terminal event is `done`, prefer the concatenated `delta.text` content as the assistant reply (that's what users saw streaming) and fall back to `done.output` only when nothing streamed (structured output, non-LLM graphs).

> **Multi-turn preview is flaky from outside the browser.** The preview endpoint uses an in-memory `dict[thread_id, InMemorySaver]`. Direct API requests (curl, `requests`) can hit different app replicas across turns, finding no checkpoint and silently restarting the graph from `__start__`. The browser playground works because of session affinity. **For multi-turn smoke tests, deploy with Lakebase and invoke the served endpoint instead** (see "Full Serving Endpoint Test" below).

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
    "conversational": "true",
    "tools_json": "[{\"type\": \"mcp_server\", \"config\": {\"server_url\": \"https://<host>/api/2.0/mcp/functions/catalog/schema\"}}]"
  }
}
```

### Node types and key config fields

| Type | Key config fields |
|------|------------------|
| `llm` | `endpoint`, `system_prompt`, `temperature`, `tools_json`, `conversational` |
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

**Decide whether you need Lakebase first.** Pass `lakebase_project_id` if the graph contains *either* a conversational LLM (`config.conversational == "true"`) *or* any `human_input` node. Without a shared checkpointer, the served endpoint silently restarts the graph from `__start__` on every request — multi-turn looks broken. Lakebase auto-provisions on first use; subsequent agents in the same project share the cluster.

```bash
curl -s -X POST "$APP_URL/api/graph/deploy" \
  -H "Content-Type: application/json" \
  -d '{
    "graph": { ...GraphDef JSON... },
    "model_name": "catalog.schema.my_test_agent",
    "experiment_path": "/Users/you@company.com/agent-sweet/my_test_agent",
    "deploy_mode": "full",
    "auth_mode": "obo",
    "pat": "'"$TOKEN"'",
    "lakebase_project_id": "agent-sweet-test"  # only if needed
  }'
```

Parse the SSE stream for `endpoint_url`, `experiment_id`, and `run_id` in the final event's `data` field. Save these — you'll need `experiment_id` to fetch the trace.

### 2. Poll for endpoint readiness

The serving endpoint takes ~10 minutes to provision (container build + cold start). Use `state.ready == "READY"` as the success signal:

```bash
HOST=https://<workspace-host>
NAME=<endpoint-name>
until s=$(curl -s "$HOST/api/2.0/serving-endpoints/$NAME" -H "Authorization: Bearer $TOKEN" | jq -r '.state.ready'); [[ "$s" == "READY" ]]; do echo "$s"; sleep 30; done; echo "READY"
```

Run this with `run_in_background: true` and you'll get a single notification when the loop exits. **Do not poll faster than every 15s** — these are real workspace API calls.

### 3. Invoke the served endpoint

Use the Responses API format (`input` is a list of role/content messages, `context.conversation_id` is the thread id for multi-turn):

```python
r = requests.post(f"{HOST}/serving-endpoints/{NAME}/invocations",
    headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    json={
        "input": [{"role": "user", "content": "Draft a coffee invite to Alex tomorrow at 2pm."}],
        "context": {"conversation_id": "smk_email_1"},
    }, timeout=240)
data = r.json()
text = next(c["text"] for item in data["output"] for c in item["content"] if c["type"] == "output_text")
```

For multi-turn, send subsequent calls with the **same** `conversation_id`. Each call is independent (synchronous `predict`), but Lakebase persists the checkpoint so the next call resumes from the previous interrupt.

### 4. Retrieve the trace

```python
import mlflow, os
os.environ["DATABRICKS_HOST"] = HOST
mlflow.set_tracking_uri("databricks")
client = mlflow.MlflowClient()
trace = client.search_traces(experiment_ids=[EXPERIMENT_ID], max_results=1)[0]

print(trace.info.status, trace.info.request_preview)
for s in trace.data.spans:
    print(f"[{s.name}] {s.status.status_code if s.status else ''}  {(s.end_time_ns - s.start_time_ns)//1_000_000}ms")
```

Verify:

- Span order matches the expected graph path (`predict → LangGraph → <Node1> → <Node2> → …`)
- LLM nodes show non-zero duration; routers and human-input nodes are typically 0–1ms
- No `ERROR` status on LLM/tool spans (see expected-error caveat below)
- For multi-turn calls, the resumed node (e.g. `Revision Notes`) appears at the start of the trace and runs in 0ms — that's the resume picking up the checkpointed interrupt value

**Expected `ERROR` spans:** `human_input` nodes always show `SpanStatusCode.ERROR` because LangGraph's `interrupt()` raises `GraphInterrupt` at the node level for control flow. The runtime catches it above and routes the interrupt event correctly. **This is not a real error** — every LangGraph app with human-in-the-loop has these in its traces.

## Common Gotchas

- **`export` env vars before `uv run python <<EOF`.** A bare assignment is shell-local; `uv` spawns a subprocess that doesn't see it. `os.environ["TOKEN"]` then `KeyError`s. Always `export TOKEN=...` first.
- **Multi-turn preview is flaky** (see callout under `/api/graph/preview`). Use the deployed endpoint for multi-turn smoke.
- **Human-input nodes need Lakebase**, not just conversational LLMs. The frontend's deploy gate enforces this; the API does not — pass `lakebase_project_id` explicitly when calling `/api/graph/deploy` directly.
- **`experiment_path` must be a sub-path inside the setup folder**, not the folder itself. Use the deploy timestamp or model slug as the leaf segment.
- **`Review Gate` / human-input ERROR spans are expected.** See "Retrieve the trace" above.
- **OAuth U2M tokens work as `pat`.** No need to mint a real PAT — `databricks auth token --profile <P>` returns a bearer token the SDK accepts for UC writes and serving-endpoint creation.
- **App must be on the right commit before testing.** After `git push`, run the sync block under "Sync the app to your branch first" to confirm the deployment commit matches `HEAD`. Skipping this is the #1 cause of "my fix isn't working."

## Smoke harness skeleton (proven pattern)

End-to-end smoke run combining preview + deploy + invoke + trace verification. Adjust to the specific change being tested:

```bash
export APP_URL="https://<host>/apps/agent-sweet-dev"
export HOST="https://<workspace-host>"
export TOKEN=$(databricks --profile <PROFILE> auth token | jq -r .access_token)
export TS=$(date +%s)

uv run python <<'EOF'
import json, os, time, requests, mlflow

APP_URL, HOST, TOKEN, TS = (os.environ[k] for k in ("APP_URL","HOST","TOKEN","TS"))
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
mlflow.set_tracking_uri("databricks")

# 1. Deploy (full + Lakebase if the graph has human_input or conversational)
deploy_body = {
    "graph": json.load(open("examples/email_draft_agent.json")),
    "model_name": f"catalog.schema.smoke_email_{TS}",
    "experiment_path": f"/Users/you@company.com/agent-sweet/smoke_email_{TS}",
    "deploy_mode": "full", "auth_mode": "obo", "pat": TOKEN,
    "lakebase_project_id": "agent-sweet-test",
}
r = requests.post(f"{APP_URL}/api/graph/deploy", headers=HEADERS, json=deploy_body, stream=True, timeout=1800)
last = None
for line in r.iter_lines():
    if line and line.decode().startswith("data: "):
        last = json.loads(line.decode()[6:])
        print(f"[{last['step']}/{last['status']}] {last['message'][:90]}")
endpoint = last["data"]["endpoint_url"].split("/")[2]
exp_id = last["data"]["experiment_id"]

# 2. Wait for READY (poll loop is best run via Bash run_in_background — omitted here)

# 3. Invoke (multi-turn flow)
thread = f"smk_{TS}"
def call(msg):
    r = requests.post(f"{HOST}/serving-endpoints/{endpoint}/invocations", headers=HEADERS,
        json={"input": [{"role":"user","content":msg}], "context":{"conversation_id":thread}}, timeout=240)
    return next(c["text"] for item in r.json()["output"] for c in item["content"] if c["type"] == "output_text")

print("Turn 1:", call("Draft a coffee invite to Alex tomorrow at 2pm.")[:120])
print("Turn 2:", call("revise")[:120])
print("Turn 3:", call("make it shorter and more casual")[:120])

# 4. Verify the trace
time.sleep(8)  # let the trace flush
trace = mlflow.MlflowClient().search_traces(experiment_ids=[exp_id], max_results=1)[0]
for s in trace.data.spans:
    print(f"  [{s.name}] {s.status.status_code if s.status else ''}")
EOF
```

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

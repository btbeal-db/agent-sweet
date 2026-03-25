"""FastAPI backend for the Agent Builder app."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import mlflow
from databricks.sdk.errors import ResourceAlreadyExists
from databricks.sdk.service.serving import (
    AiGatewayConfig,
    AiGatewayInferenceTableConfig,
    EndpointCoreConfigInput,
    ServedEntityInput,
)
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphInterrupt
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from mlflow.models.resources import (
    DatabricksFunction,
    DatabricksGenieSpace,
    DatabricksServingEndpoint,
    DatabricksTable,
    DatabricksVectorSearchIndex,
)

from langchain_core.messages import BaseMessage

from .auth import set_user_token, get_workspace_client
from .graph_builder import build_graph, run_graph
from .nodes import get_all_metadata
from .schema import (
    DeployRequest,
    DeployResponse,
    GraphDef,
    PreviewRequest,
    PreviewResponse,
)

logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).parent

_MSG_TYPE_TO_ROLE = {"human": "user", "ai": "assistant", "system": "system"}


def _serialize_messages(messages: list) -> list[dict]:
    """Convert BaseMessage objects (from add_messages reducer) to plain dicts."""
    result = []
    for msg in messages:
        if isinstance(msg, dict):
            result.append(msg)
        elif isinstance(msg, BaseMessage):
            role = _MSG_TYPE_TO_ROLE.get(msg.type, msg.type)
            entry: dict = {"role": role, "content": msg.content}
            # Preserve the node tag if present in additional_kwargs
            node = msg.additional_kwargs.get("node")
            if node:
                entry["node"] = node
            result.append(entry)
    return result


def _extract_resources(graph: GraphDef) -> list:
    """Extract Databricks resource declarations from all nodes in the graph.

    Maps node config fields to the appropriate MLflow resource types so that
    Model Serving provisions credentials (OBO) for each external resource.
    """
    resources = []
    seen = set()

    # Config field name → resource class mapping
    resource_map = {
        "endpoint": DatabricksServingEndpoint,        # LLM serving endpoints
        "endpoint_name": DatabricksServingEndpoint,   # VS endpoint names
        "index_name": DatabricksVectorSearchIndex,    # VS indexes
        "room_id": DatabricksGenieSpace,              # Genie rooms
        "table_name": DatabricksTable,                # UC tables
        "function_name": DatabricksFunction,          # UC functions
    }

    for node in graph.nodes:
        for config_key, resource_cls in resource_map.items():
            value = node.config.get(config_key)
            if value and (config_key, value) not in seen:
                seen.add((config_key, value))
                init_param = {
                    DatabricksServingEndpoint: "endpoint_name",
                    DatabricksVectorSearchIndex: "index_name",
                    DatabricksGenieSpace: "genie_space_id",
                    DatabricksTable: "table_name",
                    DatabricksFunction: "function_name",
                }[resource_cls]
                resources.append(resource_cls(**{init_param: value}))

    return resources


def _collect_code_paths() -> list[str]:
    """Copy backend/ to a clean temp directory (no __pycache__, static, etc.) for MLflow code_paths.

    MLflow code_paths needs a directory to preserve the package structure
    so that `from backend.graph_builder import ...` works in the serving container.
    """
    import shutil

    tmp = Path(tempfile.mkdtemp()) / "backend"
    shutil.copytree(
        _BACKEND_DIR,
        tmp,
        ignore=shutil.ignore_patterns("mlruns", "__pycache__", "static", "*.pyc", "*.db"),
    )
    return [str(tmp)]


app = FastAPI(title="Agent Builder", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class OBOMiddleware(BaseHTTPMiddleware):
    """Extract the user's OBO token from the x-forwarded-access-token header."""

    async def dispatch(self, request: Request, call_next):
        token = request.headers.get("x-forwarded-access-token")
        set_user_token(token)
        return await call_next(request)


app.add_middleware(OBOMiddleware)


# ── Preview session store (in-memory, per-process) ────────────────────────────

_preview_sessions: dict[str, InMemorySaver] = {}

# ── MLflow preview tracing setup ──────────────────────────────────────────────
# When deployed: use Lakebase Postgres for durable trace storage.
# When local:    use in-memory SQLite — traces live only for the process lifetime.
_lakebase_trace_conn = os.environ.get("LAKEBASE_TRACE_CONN_STRING", "")
if _lakebase_trace_conn:
    _PREVIEW_TRACKING_URI = _lakebase_trace_conn
    logger.info("MLflow playground traces → Lakebase")
else:
    _PREVIEW_TRACKING_URI = "sqlite:///:memory:"
    logger.info("MLflow playground traces → in-memory (no persistence)")

# ── API routes ────────────────────────────────────────────────────────────────


@app.get("/api/nodes")
def list_nodes():
    """Return metadata for every registered node type."""
    return get_all_metadata()


@app.post("/api/graph/validate")
def validate_graph(graph: GraphDef):
    """Basic structural validation of a graph definition."""
    errors: list[str] = []

    if not graph.nodes:
        errors.append("Graph has no nodes.")

    node_ids = {n.id for n in graph.nodes}
    valid_ids = node_ids | {"__start__", "__end__"}

    for edge in graph.edges:
        if edge.source not in valid_ids:
            errors.append(f"Edge references unknown source node: {edge.source}")
        if edge.target not in valid_ids:
            errors.append(f"Edge references unknown target node: {edge.target}")

    start_edges = [e for e in graph.edges if e.source == "__start__"]
    end_edges = [e for e in graph.edges if e.target == "__end__"]

    if not start_edges:
        errors.append("Connect the START node to at least one node.")
    if not end_edges:
        errors.append("Connect at least one node to the END node.")

    return {"valid": len(errors) == 0, "errors": errors}


def _extract_trace() -> list[dict]:
    """Grab the last MLflow trace and serialize its spans for the frontend."""
    try:
        trace_id = mlflow.get_last_active_trace_id()
        if not trace_id:
            return []
        trace = mlflow.get_trace(trace_id)
        if not trace:
            return []
        spans = []
        for span in trace.data.spans:
            entry: dict = {
                "name": span.name,
                "status": str(span.status),
                "start_time_ms": span.start_time_ns // 1_000_000 if span.start_time_ns else 0,
                "end_time_ms": span.end_time_ns // 1_000_000 if span.end_time_ns else 0,
            }
            # Include inputs/outputs but truncate large values
            if span.inputs:
                try:
                    entry["inputs"] = _truncate(span.inputs)
                except Exception:
                    entry["inputs"] = str(span.inputs)[:500]
            if span.outputs:
                try:
                    entry["outputs"] = _truncate(span.outputs)
                except Exception:
                    entry["outputs"] = str(span.outputs)[:500]
            spans.append(entry)
        return spans
    except Exception as e:
        logger.warning("Failed to extract MLflow trace: %s", e)
        return []


def _truncate(obj, max_str_len: int = 500):
    """Truncate string values in a dict/list structure for safe serialization."""
    if isinstance(obj, str):
        return obj[:max_str_len] + "..." if len(obj) > max_str_len else obj
    if isinstance(obj, dict):
        return {k: _truncate(v, max_str_len) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_truncate(item, max_str_len) for item in obj[:20]]
    return obj


@app.post("/api/graph/preview", response_model=PreviewResponse)
def preview_graph(req: PreviewRequest):
    """Build the graph and run it with a test message.

    Supports multi-turn conversations (via *thread_id*) and human-in-the-loop
    interrupts (via *resume_value*).
    """
    thread_id = req.thread_id or str(uuid.uuid4())
    if thread_id not in _preview_sessions:
        _preview_sessions[thread_id] = InMemorySaver()

    # Enable MLflow tracing for playground — use a lightweight local SQLite DB
    # so traces don't accumulate on disk or hit the workspace MLflow.
    prev_tracking_uri = mlflow.get_tracking_uri()
    mlflow.set_tracking_uri(_PREVIEW_TRACKING_URI)
    mlflow.set_experiment("playground")
    mlflow.langchain.autolog(log_traces=True)

    try:
        result = run_graph(
            req.graph,
            req.input_message,
            checkpointer=_preview_sessions[thread_id],
            thread_id=thread_id,
            resume_value=req.resume_value,
        )

        messages = _serialize_messages(result.get("messages", []))
        mlflow_trace = _extract_trace()

        interrupts = result.get("__interrupt__")
        if interrupts:
            prompt = interrupts[0].get("value", "Input needed") if isinstance(interrupts[0], dict) else str(interrupts[0].value)
            state_snapshot = {
                k: v for k, v in result.items()
                if k not in ("messages", "__interrupt__")
            }
            return PreviewResponse(
                success=True,
                interrupt=str(prompt),
                thread_id=thread_id,
                execution_trace=messages,
                state=state_snapshot,
                mlflow_trace=mlflow_trace,
            )

        state_snapshot = {
            k: v for k, v in result.items()
            if k not in ("messages", "__interrupt__")
        }
        return PreviewResponse(
            success=True,
            output=str(result.get("output", result.get("input", ""))),
            execution_trace=messages,
            state=state_snapshot,
            thread_id=thread_id,
            mlflow_trace=mlflow_trace,
        )
    except GraphInterrupt as gi:
        prompt = gi.interrupts[0].value if gi.interrupts else "Input needed"
        mlflow_trace = _extract_trace()
        return PreviewResponse(
            success=True,
            interrupt=str(prompt),
            thread_id=thread_id,
            mlflow_trace=mlflow_trace,
        )
    except Exception as e:
        logger.exception("Preview failed")
        return PreviewResponse(success=False, error=str(e))
    finally:
        # Restore previous tracking URI so deploy still points at Databricks
        mlflow.set_tracking_uri(prev_tracking_uri)


@app.get("/api/graph/load-from-run")
def load_graph_from_run(run_id: str):
    """Load a GraphDef from an MLflow run's artifacts.

    Returns run metadata and the graph definition so the frontend can
    show the user what was found before they accept.
    """
    try:
        mlflow.set_tracking_uri("databricks")

        # Fetch run metadata
        run = mlflow.get_run(run_id)
        run_name = run.info.run_name or run_id
        experiment_id = run.info.experiment_id

        import glob as _glob

        search_paths = [
            "agent/artifacts/graph_def",
            "agent/artifacts",
            "agent",
            "",
        ]
        searched = []

        for artifact_path in search_paths:
            searched.append(artifact_path or "(root)")
            try:
                local_path = mlflow.artifacts.download_artifacts(
                    run_id=run_id,
                    artifact_path=artifact_path or None,
                    tracking_uri="databricks",
                )
            except Exception:
                continue

            if Path(local_path).is_dir():
                json_files = _glob.glob(f"{local_path}/*.json")
            elif local_path.endswith(".json"):
                json_files = [local_path]
            else:
                continue

            for jf in json_files:
                try:
                    with open(jf) as f:
                        graph_data = json.load(f)
                    if "nodes" in graph_data and "edges" in graph_data:
                        graph = GraphDef.model_validate(graph_data)
                        return {
                            "success": True,
                            "graph": graph.model_dump(),
                            "run_name": run_name,
                            "experiment_id": experiment_id,
                            "found_at": artifact_path or "(root)",
                            "searched": searched,
                        }
                except (json.JSONDecodeError, Exception):
                    continue

        return {
            "success": False,
            "error": f"No graph definition found in run {run_id}.",
            "run_name": run_name,
            "searched": searched,
        }
    except Exception as e:
        logger.exception("Failed to load graph from run %s", run_id)
        return {"success": False, "error": str(e)}


@app.post("/api/graph/deploy", response_model=DeployResponse)
def deploy_graph(req: DeployRequest):
    """Log the graph as an MLflow model and create a Model Serving endpoint."""
    try:
        # 1. Validate the graph compiles
        build_graph(req.graph)

        # 2. Set up MLflow tracking and registry to point at Databricks
        mlflow.set_tracking_uri("databricks")
        mlflow.set_registry_uri("databricks-uc")
        mlflow.set_experiment(req.experiment_path)
        mlflow.langchain.autolog()

        # 3. Serialize GraphDef to a temp JSON artifact
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            f.write(req.graph.model_dump_json())
            graph_def_path = f.name

        # 4. Declare Databricks resources the model needs (enables OBO auth)
        resources = _extract_resources(req.graph)

        # 5. Log model to MLflow — use pinned requirements compiled from pyproject.toml
        requirements_path = _BACKEND_DIR.parent / "requirements-serving.txt"
        if not requirements_path.exists():
            raise FileNotFoundError(
                "requirements-serving.txt not found. Run: "
                "uv pip compile pyproject.toml -o requirements-serving.txt --python-version 3.11"
            )

        with mlflow.start_run() as run:
            model_info = mlflow.pyfunc.log_model(
                artifact_path="agent",
                python_model=str(_BACKEND_DIR / "mlflow_model.py"),
                artifacts={"graph_def": graph_def_path},
                code_paths=_collect_code_paths(),
                pip_requirements=str(requirements_path),
                resources=resources if resources else None,
            )

            # 6. Ensure catalog and schema exist, then register in UC
            parts = req.model_name.split(".")
            if len(parts) == 3:
                catalog, schema_name, _ = parts
                w = get_workspace_client()
                try:
                    w.schemas.get(f"{catalog}.{schema_name}")
                except Exception:
                    # Schema doesn't exist — try to create it
                    try:
                        w.schemas.create(name=schema_name, catalog_name=catalog)
                        logger.info("Created schema %s.%s", catalog, schema_name)
                    except Exception as schema_err:
                        logger.warning("Could not create schema: %s", schema_err)

            mv = mlflow.register_model(
                model_uri=model_info.model_uri,
                name=req.model_name,
            )
            model_version = mv.version

        # 7. Create or update serving endpoint
        w = WorkspaceClient()
        # Use just the model short name (last segment) as the endpoint name
        endpoint_name = req.model_name.split(".")[-1].replace("_", "-")

        env_vars = {}
        if req.lakebase_conn_string:
            env_vars["LAKEBASE_CONN_STRING"] = req.lakebase_conn_string

        served_entity = ServedEntityInput(
            entity_name=req.model_name,
            entity_version=str(model_version),
            environment_vars=env_vars if env_vars else None,
            scale_to_zero_enabled=True,
            workload_size="Small",
        )

        # AI Gateway inference table config (replaces legacy AutoCaptureConfig)
        parts = req.model_name.split(".")
        ai_gateway = AiGatewayConfig(
            inference_table_config=AiGatewayInferenceTableConfig(
                catalog_name=parts[0] if len(parts) >= 3 else None,
                schema_name=parts[1] if len(parts) >= 3 else None,
                table_name_prefix=endpoint_name,
                enabled=True,
            ),
        )

        try:
            w.serving_endpoints.create(
                name=endpoint_name,
                config=EndpointCoreConfigInput(
                    name=endpoint_name,
                    served_entities=[served_entity],
                ),
                ai_gateway=ai_gateway,
            )
        except ResourceAlreadyExists:
            w.serving_endpoints.update_config(
                name=endpoint_name,
                served_entities=[served_entity],
            )
            w.serving_endpoints.put_ai_gateway(
                name=endpoint_name,
                inference_table_config=AiGatewayInferenceTableConfig(
                    catalog_name=parts[0] if len(parts) >= 3 else None,
                    schema_name=parts[1] if len(parts) >= 3 else None,
                    table_name_prefix=endpoint_name,
                    enabled=True,
                ),
            )

        host = w.config.host.rstrip("/")
        endpoint_url = f"{host}/serving-endpoints/{endpoint_name}/invocations"

        return DeployResponse(
            success=True,
            endpoint_url=endpoint_url,
            model_version=str(model_version),
        )

    except Exception as e:
        logger.exception("Deploy failed")
        return DeployResponse(success=False, error=str(e))


# ── Serve frontend build ──────────────────────────────────────────────────────

static_dir = Path(__file__).parent / "static"
if static_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

"""FastAPI backend for the Agent Builder app."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .graph_builder import generate_code, run_graph
from .nodes import get_all_metadata
from .schema import ExportResponse, GraphDef, PreviewRequest, PreviewResponse

app = FastAPI(title="Agent Builder", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    for edge in graph.edges:
        if edge.source not in node_ids:
            errors.append(f"Edge references unknown source node: {edge.source}")
        if edge.target not in node_ids:
            errors.append(f"Edge references unknown target node: {edge.target}")

    # Check for entry point
    targets = {e.target for e in graph.edges}
    entry_nodes = node_ids - targets
    if not entry_nodes:
        errors.append("Graph has no entry point (every node is a target of some edge).")

    return {"valid": len(errors) == 0, "errors": errors}


@app.post("/api/graph/preview", response_model=PreviewResponse)
def preview_graph(req: PreviewRequest):
    """Build the graph and run it with a test message."""
    try:
        result = run_graph(req.graph, req.input_message)
        # Return all user-defined state variables (exclude messages)
        state_snapshot = {
            k: v for k, v in result.items() if k != "messages"
        }
        return PreviewResponse(
            success=True,
            output=str(result.get("output", result.get("user_input", ""))),
            execution_trace=result.get("messages", []),
            state=state_snapshot,
        )
    except Exception as e:
        return PreviewResponse(success=False, error=str(e))


@app.post("/api/graph/export", response_model=ExportResponse)
def export_graph(graph: GraphDef):
    """Generate a standalone Python file for this graph."""
    try:
        code = generate_code(graph)
        return ExportResponse(success=True, code=code)
    except Exception as e:
        return ExportResponse(success=False, error=str(e))


# ── Serve frontend build ──────────────────────────────────────────────────────

static_dir = Path(__file__).parent / "static"
if static_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

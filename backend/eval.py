"""Agent evaluation endpoints — wraps ``mlflow.genai.evaluate``.

The eval popup lets users:
  1. Generate or paste an eval dataset (rows of inputs + optional expectations).
  2. Pick scorers (built-in LLM judges + free-form Guidelines).
  3. Run the graph against each row and view per-row + summary assessments.

Reuses the playground MLflow tracking URI so eval runs don't pollute the
user's workspace experiments and don't require any setup beyond ``/setup``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

import mlflow
import mlflow.genai
from databricks_langchain import ChatDatabricks
from fastapi import APIRouter, HTTPException, Request as FastAPIRequest
from langchain_core.messages import HumanMessage, SystemMessage
from mlflow.genai.scorers import (
    Correctness,
    Guidelines,
    RelevanceToQuery,
    RetrievalGroundedness,
    RetrievalRelevance,
    Safety,
    Scorer,
)
from pydantic import BaseModel

from .auth import set_user_token, set_user_pat
from .graph_builder import build_graph, filter_output, prepare_invocation
from .schema import GraphDef

logger = logging.getLogger(__name__)

router = APIRouter()

_SYNTH_MODEL = "databricks-gpt-5-4-mini"


# ── Scorer catalog ────────────────────────────────────────────────────────────
#
# Built-in scorer keys exposed to the frontend. Each entry knows:
#   - how to build the scorer instance
#   - which graph features (retrieval / expectations) it needs to run
#   - a human label and description for the picker UI

_RETRIEVAL_NODE_TYPES = {"vector_search", "genie"}


class ScorerMeta(BaseModel):
    key: str
    label: str
    description: str
    requires_expectations: bool = False
    requires_retrieval: bool = False
    supports_guidelines: bool = False


_SCORER_CATALOG: list[ScorerMeta] = [
    ScorerMeta(
        key="safety",
        label="Safety",
        description="Flags harmful, offensive, or toxic content in the response.",
    ),
    ScorerMeta(
        key="relevance_to_query",
        label="Relevance to Query",
        description="Does the response directly address the user's input?",
    ),
    ScorerMeta(
        key="correctness",
        label="Correctness",
        description="Does the response match the expected facts? Requires expectations.",
        requires_expectations=True,
    ),
    ScorerMeta(
        key="retrieval_groundedness",
        label="Retrieval Groundedness",
        description="Is the response grounded in retrieved context? Requires a retrieval node.",
        requires_retrieval=True,
    ),
    ScorerMeta(
        key="retrieval_relevance",
        label="Retrieval Relevance",
        description="Were the retrieved documents relevant to the query?",
        requires_retrieval=True,
    ),
    ScorerMeta(
        key="guidelines",
        label="Guidelines",
        description="Free-form natural-language rubric the response must follow.",
        supports_guidelines=True,
    ),
]


def _build_scorer(key: str, config: dict[str, Any]) -> Scorer | None:
    if key == "safety":
        return Safety()
    if key == "relevance_to_query":
        return RelevanceToQuery()
    if key == "correctness":
        return Correctness()
    if key == "retrieval_groundedness":
        return RetrievalGroundedness()
    if key == "retrieval_relevance":
        return RetrievalRelevance()
    if key == "guidelines":
        guidelines = config.get("guidelines") or ""
        if not guidelines.strip():
            return None
        return Guidelines(name=config.get("name") or "guidelines", guidelines=guidelines)
    return None


# ── Pydantic request/response models ──────────────────────────────────────────


class EvalRow(BaseModel):
    inputs: dict[str, Any]
    expectations: dict[str, Any] | None = None


class ScorerConfig(BaseModel):
    key: str
    config: dict[str, Any] = {}


class EvalRunRequest(BaseModel):
    graph: GraphDef
    dataset: list[EvalRow]
    scorers: list[ScorerConfig]
    pat: str | None = None


class EvalRowResult(BaseModel):
    inputs: dict[str, Any]
    expectations: dict[str, Any] | None = None
    output: str
    assessments: dict[str, dict[str, Any]]
    error: str | None = None


class EvalRunResponse(BaseModel):
    run_id: str
    experiment_id: str
    summary: dict[str, float]
    rows: list[EvalRowResult]


class SuggestRequest(BaseModel):
    graph: GraphDef


class SuggestResponse(BaseModel):
    suggested: list[str]
    catalog: list[ScorerMeta]


class GenerateRequest(BaseModel):
    graph: GraphDef
    description: str = ""
    count: int = 5


class GenerateResponse(BaseModel):
    rows: list[EvalRow]


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/scorers", response_model=list[ScorerMeta])
def list_scorers() -> list[ScorerMeta]:
    return _SCORER_CATALOG


@router.post("/scorers/suggest", response_model=SuggestResponse)
def suggest_scorers(req: SuggestRequest) -> SuggestResponse:
    """Return the scorers that make sense for this graph as defaults."""
    has_retrieval = any(n.type in _RETRIEVAL_NODE_TYPES for n in req.graph.nodes)
    suggested = ["safety", "relevance_to_query"]
    if has_retrieval:
        suggested.append("retrieval_groundedness")
    return SuggestResponse(suggested=suggested, catalog=_SCORER_CATALOG)


@router.post("/dataset/generate", response_model=GenerateResponse)
def generate_dataset(req: GenerateRequest) -> GenerateResponse:
    """Generate a small synthetic eval dataset from the graph + a user description.

    Uses the SP-backed FMAPI LLM. The model is asked to produce JSON rows
    matching the graph's input state schema. ``expectations.expected_response``
    is optional and only requested for retrieval/QA-style agents.
    """
    state_summary = [
        {"name": f.name, "type": f.type, "description": f.description}
        for f in req.graph.state_fields
    ]
    node_summary = [
        {"type": n.type, "name": n.name, "writes_to": n.writes_to}
        for n in req.graph.nodes
    ]

    system = (
        "You generate evaluation datasets for AI agents. "
        "Given an agent's state schema and node graph, produce realistic test "
        "inputs the agent should handle. Output ONLY a JSON array — no prose, "
        "no markdown fences."
    )
    user = (
        f"Agent description: {req.description or '(none provided)'}\n\n"
        f"State fields: {json.dumps(state_summary)}\n"
        f"Nodes: {json.dumps(node_summary)}\n\n"
        f"Generate {req.count} diverse evaluation rows. Each row is a JSON object:\n"
        '  {"inputs": {"input": "<user query>"}, '
        '"expectations": {"expected_response": "<ideal answer or key facts>"}}\n\n'
        "The 'input' key must match the agent's primary input state field. "
        "Include 'expectations' only when an objectively correct answer exists. "
        "Mix easy and edge-case queries. Return a JSON array, nothing else."
    )

    try:
        llm = ChatDatabricks(endpoint=_SYNTH_MODEL, temperature=0.7)
        resp = llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
        text = (resp.content or "").strip()
    except Exception as exc:
        logger.exception("Synthetic dataset generation failed")
        raise HTTPException(status_code=500, detail=f"LLM call failed: {exc}") from exc

    # Strip code fences if the model added them despite instructions.
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"LLM returned non-JSON: {exc}") from exc

    rows: list[EvalRow] = []
    for entry in parsed if isinstance(parsed, list) else []:
        if not isinstance(entry, dict) or "inputs" not in entry:
            continue
        rows.append(EvalRow(inputs=entry["inputs"], expectations=entry.get("expectations")))
    return GenerateResponse(rows=rows)


def _make_predict_fn(graph: GraphDef, obo_token: str | None, pat: str | None) -> Callable:
    """Build a predict_fn closure for ``mlflow.genai.evaluate``.

    Each call captures and re-applies the request's OBO + PAT ContextVars
    because evaluate invokes predict_fn from an internal worker context.
    """

    def predict_fn(**inputs: Any) -> str:
        set_user_token(obo_token)
        set_user_pat(pat)
        try:
            input_msg = inputs.get("input")
            if not input_msg:
                # Fall back to first string value if dataset uses a different key.
                for v in inputs.values():
                    if isinstance(v, str) and v:
                        input_msg = v
                        break
            compiled = build_graph(graph)
            invoke_input, config = prepare_invocation(
                compiled, graph, input_msg or "", thread_id=None, resume_value=None,
            )
            result = compiled.invoke(invoke_input, config=config or None)
            output_text, _ = filter_output(result, graph)
            return output_text
        finally:
            set_user_pat(None)
            set_user_token(None)

    return predict_fn


def _extract_assessments(trace) -> dict[str, dict[str, Any]]:
    """Flatten a trace's assessments into ``{scorer_name: {value, rationale}}``."""
    out: dict[str, dict[str, Any]] = {}
    if not trace:
        return out
    assessments = getattr(trace.info, "assessments", None) or []
    for a in assessments:
        name = getattr(a, "name", "") or ""
        feedback = getattr(a, "feedback", None)
        value: Any = None
        if feedback is not None:
            value = getattr(feedback, "value", None)
        if value is None:
            value = getattr(a, "value", None)
        rationale = getattr(a, "rationale", "") or ""
        error = getattr(a, "error", None)
        out[name] = {
            "value": value,
            "rationale": rationale,
            "error": str(error) if error else None,
        }
    return out


def _summary_from_rows(rows: list[EvalRowResult]) -> dict[str, float]:
    """Compute mean pass-rate per scorer across rows.

    Treats ``"yes"`` / boolean True / numeric > 0 as a pass.
    """
    totals: dict[str, list[float]] = {}
    for row in rows:
        for name, a in row.assessments.items():
            val = a.get("value")
            score: float | None = None
            if isinstance(val, bool):
                score = 1.0 if val else 0.0
            elif isinstance(val, (int, float)):
                score = float(val)
            elif isinstance(val, str):
                low = val.strip().lower()
                if low in ("yes", "true", "pass"):
                    score = 1.0
                elif low in ("no", "false", "fail"):
                    score = 0.0
            if score is not None:
                totals.setdefault(name, []).append(score)
    return {name: sum(vals) / len(vals) for name, vals in totals.items() if vals}


@router.post("/run", response_model=EvalRunResponse)
def run_eval(req: EvalRunRequest, request: FastAPIRequest) -> EvalRunResponse:
    """Run ``mlflow.genai.evaluate`` against the graph and selected scorers."""
    if not req.dataset:
        raise HTTPException(status_code=400, detail="Dataset is empty.")
    if not req.scorers:
        raise HTTPException(status_code=400, detail="Pick at least one scorer.")

    scorers: list[Scorer] = []
    for sc in req.scorers:
        built = _build_scorer(sc.key, sc.config)
        if built is not None:
            scorers.append(built)
    if not scorers:
        raise HTTPException(status_code=400, detail="No valid scorers configured.")

    obo_token = request.headers.get("x-forwarded-access-token")
    predict_fn = _make_predict_fn(req.graph, obo_token, req.pat)

    data = [
        {"inputs": r.inputs, **({"expectations": r.expectations} if r.expectations else {})}
        for r in req.dataset
    ]

    # Run eval against the playground tracking DB so we don't require a
    # workspace experiment. ``main.py`` already initialized this experiment
    # at startup; we just need to point MLflow at it for this call.
    from .main import _PREVIEW_TRACKING_URI  # local import to avoid cycle

    prev_uri = mlflow.get_tracking_uri()
    mlflow.set_tracking_uri(_PREVIEW_TRACKING_URI)
    mlflow.set_experiment("playground")
    mlflow.langchain.autolog(log_traces=True)

    try:
        result = mlflow.genai.evaluate(
            data=data,
            scorers=scorers,
            predict_fn=predict_fn,
        )
        run_id = result.run_id
        run = mlflow.get_run(run_id)
        experiment_id = run.info.experiment_id

        traces = mlflow.search_traces(
            run_id=run_id,
            experiment_ids=[experiment_id],
            return_type="list",
        )
    finally:
        mlflow.set_tracking_uri(prev_uri)

    # Align traces with input rows. ``mlflow.search_traces`` returns newest
    # first; reverse so index 0 maps to dataset[0].
    traces = list(reversed(traces))

    rows: list[EvalRowResult] = []
    for i, row in enumerate(req.dataset):
        trace = traces[i] if i < len(traces) else None
        output_text = ""
        if trace and trace.data and trace.data.spans:
            root = trace.data.spans[0]
            raw_out = getattr(root, "outputs", None)
            if isinstance(raw_out, str):
                output_text = raw_out
            elif isinstance(raw_out, dict):
                output_text = raw_out.get("output") or json.dumps(raw_out, default=str)
            elif raw_out is not None:
                output_text = str(raw_out)
        rows.append(
            EvalRowResult(
                inputs=row.inputs,
                expectations=row.expectations,
                output=output_text,
                assessments=_extract_assessments(trace),
                error=None,
            )
        )

    return EvalRunResponse(
        run_id=run_id,
        experiment_id=experiment_id,
        summary=_summary_from_rows(rows),
        rows=rows,
    )

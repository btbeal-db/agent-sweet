from __future__ import annotations

import json
import logging
from typing import Any

from ..auth import get_data_client
from ..tools import _use_sdk_path
from ..tools import (
    _build_vs_meta,
    _get_mcp_client,
    _mcp_discover_and_call,
    _run_mcp_in_thread,
    _vs_mcp_url,
)
from .base import BaseNode, NodeConfigField, resolve_state
from . import register

logger = logging.getLogger(__name__)


@register
class VectorSearchNode(BaseNode):
    @property
    def node_type(self) -> str:
        return "vector_search"

    @property
    def display_name(self) -> str:
        return "Vector Search"

    @property
    def description(self) -> str:
        return "Query a Databricks Vector Search index."

    @property
    def category(self) -> str:
        return "retrieval"

    @property
    def icon(self) -> str:
        return "search"

    @property
    def color(self) -> str:
        return "#06b6d4"

    @property
    def tool_compatible(self) -> bool:
        return True

    @property
    def default_field_template(self) -> dict[str, str] | None:
        return {"name": "retrieved_docs", "type": "str", "description": "Retrieved documents"}

    @property
    def config_fields(self) -> list[NodeConfigField]:
        return [
            NodeConfigField(
                name="query_from",
                label="Query from",
                field_type="state_variable",
                default="input",
            ),
            NodeConfigField(
                name="index_name",
                label="Vector Search Index",
                placeholder="catalog.schema.my_vs_index",
                help_text="Fully qualified index name (catalog.schema.index).",
            ),
            NodeConfigField(
                name="columns",
                label="Columns to Return",
                placeholder="content, source",
                required=False,
                help_text="Comma-separated columns. Leave empty to return all columns (excluding internal __ prefixed).",
            ),
            NodeConfigField(
                name="num_results",
                label="Number of Results",
                field_type="number",
                required=False,
                default=3,
            ),
            NodeConfigField(
                name="score_threshold",
                label="Score Threshold",
                field_type="number",
                required=False,
                help_text="Minimum similarity score (0-1). Only results above this threshold are returned.",
            ),
            NodeConfigField(
                name="filters_from",
                label="Filters from",
                field_type="state_variable",
                required=False,
                help_text='State variable containing a filters JSON string. Exact match: {"department": "cardiology"}. Comparisons: {"year >=": 2020}.',
            ),
            NodeConfigField(
                name="enable_reranker",
                label="Enable Reranker",
                field_type="select",
                required=False,
                options=["true", "false"],
                default="true",
                help_text="Re-score results by relevance using the Databricks reranker.",
            ),
            NodeConfigField(
                name="columns_to_rerank",
                label="Columns to Rerank",
                required=False,
                placeholder="content, source",
                help_text="String columns for the reranker. Order matters — first 2000 chars total. If blank, reranker is skipped even when enabled.",
            ),
            NodeConfigField(
                name="query_type",
                label="Query Type",
                field_type="select",
                required=False,
                options=["ANN", "HYBRID"],
                default="ANN",
                help_text="Search algorithm: ANN (approximate nearest neighbor) or HYBRID (ANN + keyword).",
            ),
        ]

    def execute(self, state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        writes_to = config.get("_writes_to", "")
        query = resolve_state(state, config.get("query_from", "input"))
        index_name = config.get("index_name", "")

        if not index_name and not config.get("mcp_server_url"):
            return {writes_to: "Error: no Vector Search index configured."}
        if not query:
            return {writes_to: "Error: no query provided."}

        if _use_sdk_path():
            return self._execute_sdk(state, config, writes_to, query, index_name)
        return self._execute_mcp(state, config, writes_to, query, index_name)

    def _execute_sdk(
        self, state: dict, config: dict, writes_to: str, query: str, index_name: str,
    ) -> dict[str, Any]:
        """Direct SDK path — used by serving endpoints (no MCP overhead)."""
        from databricks.sdk.service.vectorsearch import (
            RerankerConfig,
            RerankerConfigRerankerParameters,
        )

        num_results = int(config.get("num_results", 3))
        columns_raw = config.get("columns", "")
        columns = [c.strip() for c in columns_raw.split(",") if c.strip()] if columns_raw else []

        score_threshold = config.get("score_threshold")
        if score_threshold is not None and score_threshold != "":
            score_threshold = float(score_threshold)
        else:
            score_threshold = None

        # Filters from state
        filters_json = None
        filters_from = config.get("filters_from")
        if filters_from:
            raw_filters = resolve_state(state, filters_from)
            if raw_filters:
                if isinstance(raw_filters, dict):
                    filters_json = json.dumps(raw_filters)
                elif isinstance(raw_filters, str):
                    try:
                        json.loads(raw_filters)
                        filters_json = raw_filters
                    except json.JSONDecodeError:
                        pass

        # Reranker
        reranker = None
        if str(config.get("enable_reranker", "true")).lower() == "true":
            rerank_cols_raw = config.get("columns_to_rerank", "")
            rerank_cols = [c.strip() for c in rerank_cols_raw.split(",") if c.strip()] if rerank_cols_raw else None
            if rerank_cols:
                reranker = RerankerConfig(
                    model="databricks_reranker",
                    parameters=RerankerConfigRerankerParameters(columns_to_rerank=rerank_cols),
                )

        try:
            w = get_data_client()
            response = w.vector_search_indexes.query_index(
                index_name=index_name, columns=columns, query_text=query,
                num_results=num_results, score_threshold=score_threshold,
                filters_json=filters_json, reranker=reranker,
            )
        except Exception as exc:
            logger.exception("VS SDK call failed (index=%s)", index_name)
            return {writes_to: f"Vector Search error: {exc}"}

        result_dict = response.as_dict()
        docs: list[str] = []
        data_chunk = result_dict.get("result", {}).get("data_array", [])
        col_names = [c["name"] for c in result_dict.get("manifest", {}).get("columns", [])]
        for row in data_chunk:
            row_parts = [f"{col_names[i]}: {row[i]}" for i in range(len(row)) if i < len(col_names)]
            docs.append("\n".join(row_parts))
        return {writes_to: "\n\n---\n\n".join(docs) if docs else "(no results)"}

    def _execute_mcp(
        self, state: dict, config: dict, writes_to: str, query: str, index_name: str,
    ) -> dict[str, Any]:
        """MCP path — used by the app preview (OBO token needs mcp.* scopes)."""
        meta = _build_vs_meta(config)

        # Dynamic filters from state
        filters_from = config.get("filters_from")
        if filters_from:
            raw_filters = resolve_state(state, filters_from)
            if raw_filters:
                if meta is None:
                    meta = {}
                if isinstance(raw_filters, dict):
                    meta["filters"] = json.dumps(raw_filters)
                elif isinstance(raw_filters, str):
                    try:
                        json.loads(raw_filters)
                        meta["filters"] = raw_filters
                    except json.JSONDecodeError:
                        pass

        try:
            url = config.get("mcp_server_url") or _vs_mcp_url(index_name)
            client = _get_mcp_client(url)
            result_text = _run_mcp_in_thread(
                _mcp_discover_and_call, url, client, {"query": str(query)},
                None, meta,
            )
        except Exception as exc:
            logger.exception("VS MCP call failed (index=%s)", index_name)
            return {writes_to: f"Vector Search error: {exc}"}

        return {writes_to: result_text}

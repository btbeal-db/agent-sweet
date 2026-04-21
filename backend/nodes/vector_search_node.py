from __future__ import annotations

import json
import logging
from typing import Any

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
        return "Query a Databricks Vector Search index via managed MCP."

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
                help_text="Fully qualified index name (catalog.schema.index). Uses managed MCP — no PAT required.",
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

        if not index_name:
            return {writes_to: "Error: no Vector Search index configured."}
        if not query:
            return {writes_to: "Error: no query provided."}

        # Build _meta from config (num_results, columns, reranker, etc.)
        meta = _build_vs_meta(config)

        # Dynamic filters from state (e.g. LLM-generated)
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
                        json.loads(raw_filters)  # validate
                        meta["filters"] = raw_filters
                    except json.JSONDecodeError:
                        logger.warning("Invalid filters JSON from '%s': %s", filters_from, raw_filters)

        try:
            url = _vs_mcp_url(index_name)
            client = _get_mcp_client(url)
            result_text = _run_mcp_in_thread(
                _mcp_discover_and_call, url, client, {"query": str(query)},
                None, meta,
            )
        except Exception as exc:
            logger.exception("VS MCP call failed (index=%s)", index_name)
            return {writes_to: f"Vector Search error: {exc}"}

        return {writes_to: result_text}

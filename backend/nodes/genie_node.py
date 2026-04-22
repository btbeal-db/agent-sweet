from __future__ import annotations

import logging
from typing import Any

from ..tools import _get_mcp_client, _genie_mcp_url, _mcp_discover_and_call, _run_mcp_in_thread
from .base import BaseNode, NodeConfigField, resolve_state
from . import register

logger = logging.getLogger(__name__)


@register
class GenieNode(BaseNode):
    @property
    def node_type(self) -> str:
        return "genie"

    @property
    def display_name(self) -> str:
        return "Genie Room"

    @property
    def description(self) -> str:
        return "Query a Databricks Genie Room via managed MCP."

    @property
    def category(self) -> str:
        return "retrieval"

    @property
    def icon(self) -> str:
        return "database"

    @property
    def color(self) -> str:
        return "#f59e0b"

    @property
    def tool_compatible(self) -> bool:
        return True

    @property
    def default_field_template(self) -> dict[str, str] | None:
        return {"name": "genie_result", "type": "str", "description": "Genie query result"}

    @property
    def config_fields(self) -> list[NodeConfigField]:
        return [
            NodeConfigField(
                name="question_from",
                label="Question from",
                field_type="state_variable",
                default="input",
            ),
            NodeConfigField(
                name="room_id",
                label="Genie Room ID",
                placeholder="01efg...",
                help_text="Genie space ID. Uses managed MCP — no PAT required.",
            ),
        ]

    def execute(self, state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        writes_to = config.get("_writes_to", "")
        query = resolve_state(state, config.get("question_from", "input"))
        room_id = config.get("room_id", "")

        if not room_id and not config.get("mcp_server_url"):
            return {writes_to: "Error: no Genie Room ID configured."}
        if not query:
            return {writes_to: "Error: no question provided."}

        try:
            url = config.get("mcp_server_url") or _genie_mcp_url(room_id)
            client = _get_mcp_client(url)
            result_text = _run_mcp_in_thread(
                _mcp_discover_and_call, url, client, {"question": str(query)},
            )
        except Exception as exc:
            logger.exception("Genie MCP call failed (room=%s)", room_id)
            return {writes_to: f"Genie error: {exc}"}

        return {writes_to: result_text}

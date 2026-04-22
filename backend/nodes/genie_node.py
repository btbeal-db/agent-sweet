from __future__ import annotations

import logging
from typing import Any

from ..auth import get_data_client
from ..tools import _get_mcp_client, _genie_mcp_url, _mcp_discover_and_call, _run_mcp_in_thread, _use_sdk_path
from .base import BaseNode, NodeConfigField, resolve_state
from . import register

logger = logging.getLogger(__name__)

MAX_ROWS = 50


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
        return "Query a Databricks Genie Room for structured data answers."

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
                help_text="Genie space ID.",
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

        if _use_sdk_path():
            return self._execute_sdk(config, writes_to, query, room_id)
        return self._execute_mcp(config, writes_to, query, room_id)

    def _execute_sdk(
        self, config: dict, writes_to: str, query: str, room_id: str,
    ) -> dict[str, Any]:
        """Direct SDK path — used by serving endpoints."""
        from databricks.sdk.service.dashboards import MessageStatus

        try:
            w = get_data_client()
            message = w.genie.start_conversation_and_wait(room_id, query)
        except Exception as exc:
            error_detail = getattr(exc, "message", str(exc))
            logger.exception("Genie SDK call failed (space=%s)", room_id)
            return {writes_to: f"Genie API error: {error_detail}"}

        if message.status == MessageStatus.FAILED:
            error_text = message.error.message if message.error else "Unknown error"
            return {writes_to: f"Genie error: {error_text}"}

        parts: list[str] = []
        for attachment in message.attachments or []:
            if attachment.text and attachment.text.content:
                parts.append(attachment.text.content)
            if attachment.query and attachment.attachment_id:
                try:
                    result = w.genie.get_message_attachment_query_result(
                        room_id, message.conversation_id,
                        message.message_id, attachment.attachment_id,
                    )
                    parts.append(self._format_query_result(attachment.query, result))
                except Exception as exc:
                    logger.exception("Failed to fetch Genie query result")
                    parts.append(f"(failed to fetch query result: {exc})")

        return {writes_to: "\n\n".join(parts) if parts else "(Genie returned no content)"}

    @staticmethod
    def _format_query_result(query_attachment, result_response) -> str:
        """Format a Genie query attachment and its results as readable text."""
        parts: list[str] = []
        if query_attachment.description:
            parts.append(query_attachment.description)
        if query_attachment.query:
            parts.append(f"```sql\n{query_attachment.query}\n```")

        stmt = result_response.statement_response if result_response else None
        if not stmt or not stmt.result or not stmt.result.data_array:
            parts.append("(no result rows)")
            return "\n\n".join(parts)

        columns = []
        if stmt.manifest and stmt.manifest.schema and stmt.manifest.schema.columns:
            columns = [c.name or f"col_{i}" for i, c in enumerate(stmt.manifest.schema.columns)]

        rows = stmt.result.data_array
        display_rows = rows[:MAX_ROWS]
        if columns:
            header = "| " + " | ".join(columns) + " |"
            sep = "| " + " | ".join("---" for _ in columns) + " |"
            table_rows = [
                "| " + " | ".join(str(v) if v is not None else "" for v in row) + " |"
                for row in display_rows
            ]
            parts.append("\n".join([header, sep, *table_rows]))

        total = stmt.manifest.total_row_count if stmt.manifest else len(rows)
        if len(rows) > MAX_ROWS:
            parts.append(f"_Showing {MAX_ROWS} of {total} rows_")
        return "\n\n".join(parts)

    def _execute_mcp(
        self, config: dict, writes_to: str, query: str, room_id: str,
    ) -> dict[str, Any]:
        """MCP path — used by the app preview."""
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

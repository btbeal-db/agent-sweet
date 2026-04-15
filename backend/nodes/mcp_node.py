from __future__ import annotations

import logging
from typing import Any

from .base import BaseNode, NodeConfigField, resolve_state
from . import register

logger = logging.getLogger(__name__)


@register
class MCPServerNode(BaseNode):
    @property
    def node_type(self) -> str:
        return "mcp_server"

    @property
    def display_name(self) -> str:
        return "MCP Server"

    @property
    def description(self) -> str:
        return "Connect to a Databricks MCP server and use its tools."

    @property
    def category(self) -> str:
        return "action"

    @property
    def icon(self) -> str:
        return "plug"

    @property
    def color(self) -> str:
        return "#f59e0b"

    @property
    def tool_compatible(self) -> bool:
        return True

    @property
    def default_field_template(self) -> dict[str, str] | None:
        return {"name": "mcp_result", "type": "str", "description": "MCP tool output"}

    @property
    def config_fields(self) -> list[NodeConfigField]:
        return [
            NodeConfigField(
                name="server_url",
                label="Server URL",
                placeholder="https://my-workspace.cloud.databricks.com/api/2.0/mcp/functions/catalog/schema",
                help_text="Databricks MCP server endpoint URL. Auth is handled automatically via your workspace credentials.",
            ),
            NodeConfigField(
                name="tool_filter",
                label="Tool Filter",
                required=False,
                placeholder="tool_a, tool_b",
                help_text="Comma-separated list of MCP tool names to expose. Leave empty for all tools.",
            ),
            NodeConfigField(
                name="tool_name",
                label="Tool Name",
                required=False,
                placeholder="my_mcp_tool",
                help_text="Standalone mode: specific MCP tool to call. Leave empty when using as an LLM tool.",
            ),
            NodeConfigField(
                name="query_from",
                label="Input from",
                field_type="state_variable",
                required=False,
                default="input",
                help_text="Standalone mode: state variable containing the tool input (passed as 'query' argument).",
            ),
        ]

    def execute(self, state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        """Standalone execution: connect to MCP server and call a specific tool."""
        writes_to = config.get("_writes_to", "")
        server_url = config.get("server_url", "")
        tool_name = config.get("tool_name", "")

        if not server_url:
            return {
                writes_to: "Error: no MCP server URL configured.",
                "messages": [{"role": "system", "content": "MCP Server: missing server_url.", "node": "mcp_server"}],
            }
        if not tool_name:
            return {
                writes_to: "Error: no tool_name configured for standalone MCP node.",
                "messages": [{"role": "system", "content": "MCP Server: missing tool_name for standalone execution.", "node": "mcp_server"}],
            }

        query = resolve_state(state, config.get("query_from", "input"))

        try:
            import asyncio
            from databricks_langchain import DatabricksMCPServer, DatabricksMultiServerMCPClient
            from ..auth import get_data_client
            from ..tools import _run_mcp_in_thread

            def _call():
                w = get_data_client()
                client = DatabricksMultiServerMCPClient([
                    DatabricksMCPServer(name="mcp", url=server_url, workspace_client=w),
                ])
                tools = asyncio.run(client.get_tools())
                tool_fn = next((t for t in tools if t.name == tool_name), None)
                if not tool_fn:
                    available = [t.name for t in tools]
                    return f"Tool '{tool_name}' not found. Available: {available}"
                return asyncio.run(tool_fn.ainvoke({"query": str(query)}))

            result = _run_mcp_in_thread(_call)
            if isinstance(result, list):
                parts = [b.get("text", "") if isinstance(b, dict) else str(b) for b in result
                         if not isinstance(b, dict) or b.get("type") == "text"]
                result_text = "\n".join(p for p in parts if p) or str(result)
            else:
                result_text = str(result)

        except Exception as exc:
            logger.exception("MCP tool call failed (server=%s, tool=%s)", server_url, tool_name)
            return {
                writes_to: f"MCP Server error: {exc}",
                "messages": [{"role": "system", "content": f"MCP Server error: {exc}", "node": "mcp_server"}],
            }

        return {
            writes_to: result_text,
            "messages": [
                {"role": "system", "content": f"[MCP: {tool_name}]\n{result_text}", "node": "mcp_server"}
            ],
        }

from __future__ import annotations

import json
import logging
from typing import Any

from ..auth import get_data_client, is_serving
from ..tools import _get_mcp_client, _mcp_discover_and_call, _run_mcp_in_thread, _uc_function_mcp_url
from .base import BaseNode, NodeConfigField, resolve_state
from . import register

logger = logging.getLogger(__name__)


@register
class UCFunctionNode(BaseNode):
    @property
    def node_type(self) -> str:
        return "uc_function"

    @property
    def display_name(self) -> str:
        return "UC Function"

    @property
    def description(self) -> str:
        return "Execute a Unity Catalog function."

    @property
    def category(self) -> str:
        return "action"

    @property
    def icon(self) -> str:
        return "function-square"

    @property
    def color(self) -> str:
        return "#8b5cf6"

    @property
    def tool_compatible(self) -> bool:
        return True

    @property
    def default_field_template(self) -> dict[str, str] | None:
        return {"name": "function_result", "type": "str", "description": "Function output"}

    @property
    def config_fields(self) -> list[NodeConfigField]:
        return [
            NodeConfigField(
                name="function_name",
                label="UC Function",
                placeholder="catalog.schema.function_name",
                help_text="Fully qualified UC function name.",
            ),
            NodeConfigField(
                name="parameters_from",
                label="Parameters from",
                field_type="state_variable",
                required=False,
                help_text="State variable containing a JSON object of function parameters. If not set, the function is called with no arguments.",
            ),
        ]

    def execute(self, state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        writes_to = config.get("_writes_to", "")
        function_name = config.get("function_name", "")

        if not function_name and not config.get("mcp_server_url"):
            return {writes_to: "Error: no UC function configured."}

        # Resolve parameters from state
        params: dict[str, Any] = {}
        params_from = config.get("parameters_from")
        if params_from:
            raw_params = resolve_state(state, params_from)
            if raw_params:
                if isinstance(raw_params, dict):
                    params = raw_params
                elif isinstance(raw_params, str):
                    try:
                        params = json.loads(raw_params)
                    except json.JSONDecodeError:
                        logger.warning("Invalid parameters JSON from '%s': %s", params_from, raw_params)

        if is_serving():
            return self._execute_sdk(writes_to, function_name, params)
        return self._execute_mcp(config, writes_to, function_name, params)

    def _execute_sdk(
        self, writes_to: str, function_name: str, params: dict,
    ) -> dict[str, Any]:
        """Direct SDK path — used by serving endpoints."""
        from databricks_langchain import UCFunctionToolkit
        from databricks_langchain.uc_ai import DatabricksFunctionClient

        try:
            w = get_data_client()
            client = DatabricksFunctionClient(client=w)
            toolkit = UCFunctionToolkit(function_names=[function_name], client=client)
            tools = toolkit.tools
            if not tools:
                return {writes_to: f"Error: function '{function_name}' not found."}
            result = tools[0].invoke(params)
        except Exception as exc:
            logger.exception("UC Function SDK call failed (function=%s)", function_name)
            return {writes_to: f"UC Function error: {exc}"}

        return {writes_to: result if isinstance(result, str) else json.dumps(result, indent=2)}

    def _execute_mcp(
        self, config: dict, writes_to: str, function_name: str, params: dict,
    ) -> dict[str, Any]:
        """MCP path — used by the app preview."""
        try:
            url = config.get("mcp_server_url") or _uc_function_mcp_url(function_name)
            client = _get_mcp_client(url)
            result_text = _run_mcp_in_thread(
                _mcp_discover_and_call, url, client, params,
            )
        except Exception as exc:
            logger.exception("UC Function MCP call failed (function=%s)", function_name)
            return {writes_to: f"UC Function error: {exc}"}

        return {writes_to: result_text}

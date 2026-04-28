from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import Field, create_model
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from databricks_langchain import ChatDatabricks

from .base import BaseNode, NodeConfigField
from . import register

logger = logging.getLogger(__name__)

_TYPE_MAP: dict[str, type] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list[str]": list[str],
    "list[int]": list[int],
    "list[float]": list[float],
}


def build_pydantic_model(sub_fields: list[dict[str, str]], model_name: str = "StructuredOutput") -> type | None:
    """Build a Pydantic model from sub-field definitions."""
    if not sub_fields:
        return None

    field_definitions: dict[str, Any] = {}
    for f in sub_fields:
        name = f.get("name", "").strip()
        type_str = f.get("type", "str").strip()
        desc = f.get("description", "")
        if not name:
            continue
        py_type = _TYPE_MAP.get(type_str, str)
        field_definitions[name] = (py_type, Field(description=desc))

    if not field_definitions:
        return None

    return create_model(model_name, **field_definitions)


_TEMPLATE_SKIP_KEYS = {"messages", "_writes_to", "_target_field"}


def _resolve_templates(template: str, state: dict[str, Any]) -> str:
    """Replace ``{field}`` and ``{field.sub}`` placeholders with state values.

    Sub-paths (e.g. ``{verdict.reasoning}``) resolve against fields whose
    value is a JSON-encoded structured output. Unknown placeholders are left
    in place so the user notices the typo.
    """
    for key, val in state.items():
        if key in _TEMPLATE_SKIP_KEYS:
            continue
        template = template.replace(f"{{{key}}}", str(val))
        if isinstance(val, str) and val.strip().startswith("{"):
            try:
                parsed = json.loads(val)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(parsed, dict):
                for sub_key, sub_val in parsed.items():
                    template = template.replace(f"{{{key}.{sub_key}}}", str(sub_val))
    return template


def _get_message_history(state: dict[str, Any], last_n: int = 0) -> list[BaseMessage]:
    """Extract user/assistant message objects from state for the LLM context.

    Filters to only HumanMessage and AIMessage — skips system, tool, and
    any non-standard messages that other nodes may have added.
    """
    messages: list[BaseMessage] = []
    for msg in state.get("messages", []):
        if isinstance(msg, (HumanMessage, AIMessage)):
            messages.append(msg)
        elif isinstance(msg, dict):
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))

    if last_n and last_n > 0:
        messages = messages[-last_n:]

    return messages


def _build_schema_instruction(sub_fields: list[dict[str, str]], field_name: str) -> str:
    """Build a prompt section describing the expected structured output."""
    lines = [f"You must respond with a structured `{field_name}` object containing:"]
    for f in sub_fields:
        name = f.get("name", "")
        type_str = f.get("type", "str")
        desc = f.get("description", "")
        if not name:
            continue
        lines.append(f"- {name} ({type_str}): {desc}" if desc else f"- {name} ({type_str})")
    return "\n".join(lines)


@register
class LLMNode(BaseNode):
    @property
    def node_type(self) -> str:
        return "llm"

    @property
    def display_name(self) -> str:
        return "LLM"

    @property
    def description(self) -> str:
        return "Call a Databricks Foundation Model or external LLM endpoint."

    @property
    def category(self) -> str:
        return "model"

    @property
    def icon(self) -> str:
        return "brain"

    @property
    def color(self) -> str:
        return "#8b5cf6"

    @property
    def config_fields(self) -> list[NodeConfigField]:
        return [
            NodeConfigField(
                name="endpoint",
                label="Serving Endpoint",
                field_type="searchable_select",
                fetch_endpoint="/api/discover/serving-endpoints",
                placeholder="databricks-meta-llama-3-3-70b-instruct",
            ),
            NodeConfigField(
                name="system_prompt",
                label="System Prompt",
                field_type="textarea",
                required=False,
                default="You are a helpful assistant.",
            ),
            NodeConfigField(
                name="temperature",
                label="Temperature",
                field_type="number",
                required=False,
                default=0.7,
            ),
            NodeConfigField(
                name="conversational",
                label="Conversational",
                field_type="select",
                required=False,
                default="false",
                options=["false", "true"],
                help_text="Multi-turn awareness — pass prior user/assistant messages to the LLM each turn.",
            ),
            NodeConfigField(
                name="last_n_messages",
                label="Last N Messages",
                field_type="number",
                required=False,
                default=0,
                help_text="Cap on prior messages to include (0 = all). Only used when Conversational is enabled.",
                advanced=True,
            ),
            NodeConfigField(
                name="output_schema",
                label="Structured Output",
                field_type="schema_editor",
                required=False,
                default=[],
                help_text="Define structured output fields. Leave empty for plain text output.",
                advanced=True,
            ),
        ]

    def execute(self, state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        writes_to = config.get("_writes_to", "")
        endpoint = config.get("endpoint", "databricks-meta-llama-3-3-70b-instruct")
        temperature = float(config.get("temperature", 0.7))
        raw_prompt = config.get("system_prompt", "You are a helpful assistant.")
        conversational = str(config.get("conversational", "false")).lower() == "true"
        last_n = int(config.get("last_n_messages", 0) or 0)

        # Resolve {field} / {field.sub} placeholders against current state.
        system_prompt = _resolve_templates(raw_prompt, state)

        # LLM calls use the SP credentials (default env vars). FMAPI's data-plane
        # does not accept OBO tokens. Data-access nodes (VS, Genie, UC) use OBO.
        llm = ChatDatabricks(endpoint=endpoint, temperature=temperature)

        # Bind tools if configured
        tools_json_raw = config.get("tools_json", "")
        tools = []
        if tools_json_raw and str(tools_json_raw).strip():
            try:
                from ..tools import make_tools_from_json
                tools = make_tools_from_json(str(tools_json_raw))
                if not tools:
                    logger.error(
                        "tools_json was configured but no tools were created — "
                        "the LLM will proceed without tools. tools_json=%s",
                        str(tools_json_raw)[:200],
                    )
                else:
                    logger.info("Bound %d tools: %s", len(tools), [t.name for t in tools])
                    llm = llm.bind_tools(tools)
            except Exception as exc:
                return {writes_to: f"Error binding tools: {exc}"}

        # Structured output is configured directly on the node. Empty schema = plain text.
        raw_schema = config.get("output_schema", [])
        if isinstance(raw_schema, str):
            try:
                raw_schema = json.loads(raw_schema)
            except (json.JSONDecodeError, ValueError):
                raw_schema = []
        sub_fields = [f for f in raw_schema if isinstance(f, dict) and f.get("name")] if isinstance(raw_schema, list) else []

        # In conversational mode, pass prior user/assistant turns as real
        # message objects. Otherwise treat each invocation as a single turn.
        if conversational:
            messages_for_llm = [SystemMessage(content=system_prompt)] + _get_message_history(state, last_n=last_n)
        else:
            messages_for_llm = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=state.get("input", "")),
            ]

        # Structured output path
        if sub_fields and writes_to:
            model_cls = build_pydantic_model(sub_fields, model_name=writes_to.title().replace("_", ""))
            if model_cls is None:
                return {writes_to: "Error: structured field has no valid sub-fields"}

            schema_instruction = _build_schema_instruction(sub_fields, writes_to)
            messages_for_llm[0] = SystemMessage(
                content=f"{system_prompt}\n\n{schema_instruction}"
            )

            structured_llm = llm.with_structured_output(model_cls)
            result = structured_llm.invoke(messages_for_llm)

            result_dict = result.model_dump()
            response_text = json.dumps(result_dict, indent=2)

            return {
                writes_to: response_text,
                "messages": [AIMessage(content=response_text)],
            }

        # Plain text / tool-calling path — loop stays local, only
        # the final AIMessage is returned to state.
        max_iterations = int(config.get("max_tool_iterations", 10) or 10)

        for _ in range(max_iterations):
            response = llm.invoke(messages_for_llm)

            if not tools or not hasattr(response, "tool_calls") or not response.tool_calls:
                return {
                    writes_to: response.content,
                    "messages": [AIMessage(content=response.content)],
                }

            # Tool-calling loop — intermediates stay local
            messages_for_llm.append(response)
            tool_map = {t.name: t for t in tools}
            for tool_call in response.tool_calls:
                tool_name = tool_call.get("name", "")
                tool_args = tool_call.get("args", {})
                tool_id = tool_call.get("id", "")

                tool_fn = tool_map.get(tool_name)
                if not tool_fn:
                    result_str = f"Unknown tool: {tool_name}"
                else:
                    try:
                        result = tool_fn.invoke(tool_args)
                        result_str = result if isinstance(result, str) else json.dumps(result, default=str)
                    except Exception as exc:
                        result_str = f"Error calling {tool_name}: {exc}"

                messages_for_llm.append(ToolMessage(content=result_str, tool_call_id=tool_id))

        return {
            writes_to: "(max tool iterations reached)",
            "messages": [AIMessage(content="(max tool iterations reached)")],
        }

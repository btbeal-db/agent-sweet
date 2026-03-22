from __future__ import annotations

import json
from typing import Any

from pydantic import Field, create_model
from databricks_langchain import ChatDatabricks
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from .base import BaseNode, NodeConfigField
from . import register

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


def _resolve_templates(template: str, state: dict[str, Any]) -> str:
    """Replace {field_name} placeholders in the template with state values."""
    result = template
    for key, val in state.items():
        if key in ("messages", "_writes_to", "_target_field"):
            continue
        result = result.replace(f"{{{key}}}", str(val))
    return result


def _build_state_context(state: dict[str, Any]) -> str:
    """Format non-empty state fields as context for the LLM prompt."""
    parts = []
    for key, val in state.items():
        if key in ("messages", "_writes_to", "_target_field") or not val:
            continue
        parts.append(f"{key}: {val}")
    return "\n".join(parts)


def _format_conversation_history(state: dict[str, Any], last_n: int = 0) -> str:
    """Format prior user/assistant turns as a readable text block.

    Args:
        state: The full agent state (messages may be BaseMessage or dict).
        last_n: Number of recent messages to include. 0 means all.

    Returns:
        A formatted string like:
            User: hello
            Assistant: Hi there!
    """
    _TYPE_TO_ROLE = {"human": "User", "ai": "Assistant"}
    turns: list[str] = []
    for msg in state.get("messages", []):
        if isinstance(msg, BaseMessage):
            role = _TYPE_TO_ROLE.get(msg.type)
            if role:
                turns.append(f"{role}: {msg.content}")
        elif isinstance(msg, dict):
            role = msg.get("role", "")
            if role in ("user", "assistant"):
                label = "User" if role == "user" else "Assistant"
                turns.append(f"{label}: {msg.get('content', '')}")

    if last_n and last_n > 0:
        turns = turns[-last_n:]

    return "\n".join(turns)


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
                help_text="Include conversation history in the prompt for multi-turn awareness.",
            ),
            NodeConfigField(
                name="last_n_messages",
                label="Last N Messages",
                field_type="number",
                required=False,
                default=0,
                help_text="Number of recent messages to include (0 = all). Only used when Conversational is enabled.",
            ),
        ]

    def execute(self, state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        writes_to = config.get("_writes_to", "")
        target_field = config.get("_target_field")
        endpoint = config.get("endpoint", "databricks-meta-llama-3-3-70b-instruct")
        temperature = float(config.get("temperature", 0.7))
        raw_prompt = config.get("system_prompt", "You are a helpful assistant.")
        conversational = str(config.get("conversational", "false")).lower() == "true"
        last_n = int(config.get("last_n_messages", 0) or 0)

        # Resolve {field_name} templates in the system prompt from state
        system_prompt = _resolve_templates(raw_prompt, state)
        state_context = _build_state_context(state)

        # Optionally append conversation history to the context
        if conversational:
            history_text = _format_conversation_history(state, last_n=last_n)
            if history_text:
                state_context = f"{state_context}\n\nConversation History:\n{history_text}" if state_context else f"Conversation History:\n{history_text}"

        llm = ChatDatabricks(endpoint=endpoint, temperature=temperature)

        # Auto-detect structured output from the state field definition
        is_structured = target_field is not None and getattr(target_field, "type", "") == "structured"

        if is_structured:
            sub_fields = getattr(target_field, "sub_fields", [])
            model_cls = build_pydantic_model(sub_fields, model_name=writes_to.title().replace("_", ""))
            if model_cls is None:
                return {
                    writes_to: "Error: structured field has no valid sub-fields",
                    "messages": [{"role": "system", "content": "LLM: invalid structured field schema.", "node": "llm"}],
                }

            # Auto-inject schema description so the LLM knows what to produce
            schema_instruction = _build_schema_instruction(sub_fields, writes_to)
            system_prompt = f"{system_prompt}\n\n{schema_instruction}"

            structured_llm = llm.with_structured_output(model_cls)
            result = structured_llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=state_context or state.get("input", "")),
            ])

            result_dict = result.model_dump()
            response_text = json.dumps(result_dict, indent=2)

            return {
                writes_to: response_text,
                "messages": [
                    {"role": "assistant", "content": f"[LLM → {writes_to}] {response_text}", "node": "llm"},
                ],
            }

        # Plain text path
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=state_context or state.get("input", "")),
        ])
        response_text = response.content

        return {
            writes_to: response_text,
            "messages": [{"role": "assistant", "content": response_text, "node": "llm"}],
        }

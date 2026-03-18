from __future__ import annotations

import json
from typing import Any

from .base import BaseNode, NodeConfigField
from . import register


def _parse_routes(config: dict[str, Any]) -> list[dict[str, str]]:
    raw = config.get("routes_json", "[]")
    if isinstance(raw, list):
        return raw
    try:
        routes = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(routes, list):
        return []
    return routes


def _try_parse_json(text: str) -> dict | None:
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def _match_json_field(parsed: dict, field_name: str, expected: str) -> bool:
    if field_name not in parsed:
        return False
    actual = parsed[field_name]
    expected_lower = expected.strip().lower()
    actual_str = str(actual).strip().lower()
    if actual_str == expected_lower:
        return True
    if isinstance(actual, bool):
        return expected_lower in ("true", "1", "yes") if actual else expected_lower in ("false", "0", "no")
    return False


@register
class RouterNode(BaseNode):
    @property
    def node_type(self) -> str:
        return "router"

    @property
    def display_name(self) -> str:
        return "Router"

    @property
    def description(self) -> str:
        return "Conditional edge — route based on keywords or structured output fields."

    @property
    def category(self) -> str:
        return "control"

    @property
    def icon(self) -> str:
        return "git-branch"

    @property
    def color(self) -> str:
        return "#ef4444"

    @property
    def config_fields(self) -> list[NodeConfigField]:
        return [
            NodeConfigField(
                name="evaluates",
                label="Evaluates",
                field_type="state_variable",
                default="user_input",
            ),
            NodeConfigField(
                name="routes_json",
                label="Routes",
                field_type="route_editor",
                required=True,
                default='[{"name": "default", "condition_type": "keywords", "condition": "", "json_field": "", "json_value": ""}]',
            ),
        ]

    @property
    def is_router(self) -> bool:
        return True

    def get_route_names(self, config: dict[str, Any]) -> list[str]:
        return [r["name"] for r in _parse_routes(config) if r.get("name")]

    def execute(self, state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        eval_var = config.get("evaluates", "user_input")
        input_text = state.get(eval_var, "")
        routes = _parse_routes(config)

        if not routes:
            return {
                "_route": "default",
                "messages": [{"role": "system", "content": "Router: no routes defined.", "node": "router"}],
            }

        parsed_json = _try_parse_json(input_text)
        chosen = routes[-1].get("name", "default")
        match_reason = "fallback"

        for route in routes:
            condition_type = route.get("condition_type", "keywords")
            if condition_type == "json_field":
                field_name = route.get("json_field", "").strip()
                expected = route.get("json_value", "").strip()
                if not field_name:
                    continue
                if parsed_json is not None and _match_json_field(parsed_json, field_name, expected):
                    chosen = route["name"]
                    match_reason = f"field '{field_name}' = {expected}"
                    break
            else:
                condition = route.get("condition", "").strip()
                if not condition:
                    continue
                keywords = [kw.strip().lower() for kw in condition.split(",") if kw.strip()]
                if any(kw in input_text.lower() for kw in keywords):
                    chosen = route["name"]
                    match_reason = "keyword match"
                    break

        return {
            "_route": chosen,
            "messages": [{"role": "system", "content": f"Router chose path: {chosen} ({match_reason})", "node": "router"}],
        }

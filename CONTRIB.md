# Contributing a New Node

The agent builder uses auto-discovery — most of the integration is automatic. Here's the minimal checklist.

## Required

### 1. Create the node file

Add `backend/nodes/your_node.py`:

```python
from __future__ import annotations
from typing import Any
from .base import BaseNode, NodeConfigField
from . import register

@register
class YourNode(BaseNode):
    @property
    def node_type(self) -> str:
        return "your_node"

    @property
    def display_name(self) -> str:
        return "Your Node"

    @property
    def description(self) -> str:
        return "One-line description shown in the palette."

    @property
    def category(self) -> str:
        return "action"  # model | retrieval | action | control

    @property
    def icon(self) -> str:
        return "puzzle"  # must be in NodeIcon.tsx ICON_MAP

    @property
    def color(self) -> str:
        return "#6366f1"  # hex color for the node header

    @property
    def config_fields(self) -> list[NodeConfigField]:
        return [
            NodeConfigField(name="param1", label="Param 1"),
        ]

    def execute(self, state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        writes_to = config.get("_writes_to", "")
        # ... your logic ...
        return {
            writes_to: result,
            "messages": [{"role": "system", "content": "...", "node": "your_node"}],
        }
```

That's it for the backend. The `@register` decorator + `pkgutil` auto-import in `__init__.py` handles discovery. The node will appear in the palette and config panel automatically.

### 2. Add icon mapping (if using a new icon)

In `frontend/src/components/NodeIcon.tsx`, add your icon to `ICON_MAP`:

```tsx
import { YourIcon } from "lucide-react";
// ...
const ICON_MAP = {
  // ...existing...
  "your-icon": YourIcon,
};
```

Unmapped icons fall back to the puzzle piece. Browse options at [lucide.dev](https://lucide.dev).

### 3. Add resource declarations (if accessing Databricks resources)

If your node references external resources (endpoints, tables, functions, etc.), update `backend/main.py` so Model Serving provisions credentials:

1. Import the MLflow resource class
2. Add to `resource_map` in `_extract_resources()`
3. Add to `init_param` mapping

Available resource classes:
| Class | Config field example | Used by |
|---|---|---|
| `DatabricksServingEndpoint` | `endpoint`, `endpoint_name` | LLM, Vector Search |
| `DatabricksVectorSearchIndex` | `index_name` | Vector Search |
| `DatabricksGenieSpace` | `room_id` | Genie |
| `DatabricksFunction` | `function_name` | UC Function |
| `DatabricksTable` | `table_name` | — |

## Optional (recommended)

### 4. Add a homepage card

In `frontend/src/components/HomePage.tsx`:
- Add a card in the "Available components" section
- Add a permission entry if your node requires specific Databricks access

## Config field types

The config panel renders fields automatically based on `field_type`:

| `field_type` | Renders as | Notes |
|---|---|---|
| `"text"` | Text input | Default |
| `"number"` | Number input | |
| `"textarea"` | Multi-line text | |
| `"select"` | Dropdown | Provide `options` list |
| `"state_variable"` | Dropdown of state vars | Supports dot-path for structured fields |
| `"schema_editor"` | Structured field editor | For LLM structured output |
| `"route_editor"` | Route builder | Router nodes only |

## Reading from state

Use `resolve_state()` from `base.py` when your node reads from a user-selected state variable. It handles both flat keys (`"input"`) and dot-paths into structured fields (`"output.query_filters"`):

```python
from .base import resolve_state

query = resolve_state(state, config.get("query_from", "input"))
```

## Router nodes

If your node branches the graph:

1. Add `is_router = True` property
2. Implement `get_route_names(config) -> list[str]`
3. Return `{"_route": chosen_key}` from `execute()`

See `backend/nodes/router_node.py` for reference.

## Execute contract

Your `execute()` receives:
- `state` — full agent state dict
- `config` — user-supplied config values, plus `_writes_to` (target state field) and `_target_field` (the `StateFieldDef`)

It must return a dict with:
- `writes_to: value` — the result to write into the target state field
- `"messages": [...]` — list of message dicts for the execution trace (each with `role`, `content`, `node`)

## Summary

| What | Where | Required? |
|---|---|---|
| Node class with `@register` | `backend/nodes/your_node.py` | Yes |
| Icon mapping | `frontend/src/components/NodeIcon.tsx` | Only if new icon |
| Resource declarations | `backend/main.py` | Only if external resources |
| Homepage card + permissions | `frontend/src/components/HomePage.tsx` | Recommended |

"""Translates a visual graph definition into a runnable LangGraph."""

from __future__ import annotations

import json
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command

from .nodes import get_node
from .schema import GraphDef, StateFieldDef

# Maps visual canvas IDs to LangGraph constants
_SENTINEL = {"__start__": START, "__end__": END}


def _build_state_type(state_fields: list[StateFieldDef]) -> type:
    """Dynamically create a TypedDict from the state model."""
    fields: dict[str, type] = {}
    for sf in state_fields:
        fields[sf.name] = str  # all state values are strings at runtime
    # Use add_messages reducer so the checkpointer accumulates messages across turns
    fields["messages"] = Annotated[list, add_messages]
    return TypedDict("AgentState", fields)  # type: ignore[misc]


def _make_node_fn(
    node_impl,
    config: dict[str, Any],
    writes_to: str,
    target_field: StateFieldDef | None,
    graph_name: str,
):
    """Create a closure so each graph node captures its own config.

    Returns only the state *updates* — LangGraph merges them into state.
    """

    def fn(state: dict[str, Any]) -> dict[str, Any]:
        enriched_config = {
            **config,
            "_writes_to": writes_to,
            "_target_field": target_field,
        }
        updates = node_impl.execute(state, enriched_config)
        return updates

    fn.__name__ = graph_name
    return fn


def _make_router_fn(node_impl, config: dict[str, Any], graph_name: str):
    """Create a routing function that returns the chosen route key."""

    def fn(state: dict[str, Any]) -> str:
        result = node_impl.execute(state, config)
        return result.get("_route", "default")

    fn.__name__ = graph_name
    return fn


def _resolve(node_id: str) -> str:
    """Map a canvas node ID to a LangGraph node reference."""
    return _SENTINEL.get(node_id, node_id)


def _graph_name(node_def) -> str:
    """Pick a human-readable name for tracing.

    Priority: explicit user name → ``writes_to`` slug → typed canvas id.
    The slug fallback covers nodes the user dropped without renaming
    (e.g. ``llm``, ``llm_2``); the typed-id fallback only fires for
    routers, which have no ``writes_to``.
    """
    if node_def.name and node_def.name.strip():
        return node_def.name.strip()
    if node_def.writes_to:
        return node_def.writes_to
    suffix = node_def.id.replace("node_", "") if node_def.id.startswith("node_") else node_def.id
    return f"{node_def.type}_{suffix}" if suffix else node_def.type


def build_graph(graph_def: GraphDef, checkpointer=None):
    """Build a compiled LangGraph StateGraph from a GraphDef."""

    state_type = _build_state_type(graph_def.state_fields)
    builder = StateGraph(state_type)

    node_map = {n.id: n for n in graph_def.nodes}

    # Map canvas IDs to LangGraph node names (user name or fallback to ID)
    name_of: dict[str, str] = {n.id: _graph_name(n) for n in graph_def.nodes}

    # Validate that START and END are connected
    entry_edges = [e for e in graph_def.edges if e.source == "__start__"]
    exit_edges = [e for e in graph_def.edges if e.target == "__end__"]

    if not entry_edges:
        raise ValueError("Connect the START node to at least one node.")
    if not exit_edges:
        raise ValueError("Connect at least one node to the END node.")

    # Register all nodes and identify routers
    router_nodes: set[str] = set()
    for node_def in graph_def.nodes:
        node_impl = get_node(node_def.type)
        gname = name_of[node_def.id]
        if getattr(node_impl, "is_router", False):
            router_nodes.add(node_def.id)

        target_field = graph_def.get_state_field(node_def.writes_to)
        builder.add_node(
            gname,
            _make_node_fn(node_impl, node_def.config, node_def.writes_to, target_field, gname),
        )

    def _resolve_named(node_id: str) -> str:
        """Map a canvas ID to its LangGraph name, handling sentinels."""
        sentinel = _SENTINEL.get(node_id)
        if sentinel is not None:
            return sentinel
        return name_of.get(node_id, node_id)

    # Group all outgoing edges by source (excluding __start__)
    outgoing: dict[str, list] = {}
    for edge in graph_def.edges:
        if edge.source == "__start__":
            continue
        outgoing.setdefault(edge.source, []).append(edge)

    # Wire START → entry nodes
    for edge in entry_edges:
        builder.add_edge(START, _resolve_named(edge.target))

    # Wire all other edges
    for source_id, edges in outgoing.items():
        src_name = name_of.get(source_id, source_id)
        if source_id in router_nodes:
            node_def = node_map[source_id]
            node_impl = get_node(node_def.type)
            route_map = {
                (e.source_handle or "default"): _resolve_named(e.target)
                for e in edges
            }
            builder.add_conditional_edges(
                src_name,
                _make_router_fn(node_impl, node_def.config, src_name),
                route_map,
            )
        else:
            for edge in edges:
                builder.add_edge(src_name, _resolve_named(edge.target))

    return builder.compile(checkpointer=checkpointer)


def prepare_invocation(
    compiled,
    graph_def: GraphDef,
    input_message: str,
    thread_id: str | None,
    resume_value: str | None,
) -> tuple[Any, dict[str, Any]]:
    """Build the (input, config) pair for ``compiled.invoke`` / ``compiled.stream``.

    Continuations on an existing thread send only the new user message so the
    checkpointer's prior state survives; fresh threads send the full initial
    state. Resumes wrap the value in ``Command(resume=...)``.
    """
    config: dict[str, Any] = {}
    if thread_id is not None:
        config["configurable"] = {"thread_id": thread_id}

    if resume_value is not None:
        return Command(resume=resume_value), config

    has_history = False
    if thread_id:
        existing = compiled.get_state(config)
        if existing and existing.values:
            has_history = True

    if has_history:
        return (
            {
                "input": input_message,
                "messages": [{"role": "user", "content": input_message}],
            },
            config,
        )

    initial_state: dict[str, Any] = {f.name: "" for f in graph_def.state_fields}
    initial_state["input"] = input_message
    initial_state["messages"] = [{"role": "user", "content": input_message}]
    return initial_state, config


def run_graph(
    graph_def: GraphDef,
    input_message: str,
    checkpointer=None,
    thread_id: str | None = None,
    resume_value: str | None = None,
) -> dict[str, Any]:
    """Build and invoke the graph with a user message.

    When *resume_value* is provided the graph is resumed from an interrupt
    using ``Command(resume=...)``.  Otherwise a fresh invocation is started.

    When a *checkpointer* and *thread_id* are provided and the thread already
    has checkpoint state, only the new user message is sent so that prior
    conversation history is preserved by the checkpointer.
    """
    compiled = build_graph(graph_def, checkpointer=checkpointer)
    invoke_input, config = prepare_invocation(
        compiled, graph_def, input_message, thread_id, resume_value
    )
    return compiled.invoke(invoke_input, config=config or None)


def _resolve_field(result: dict[str, Any], field_path: str) -> tuple[str, Any]:
    """Resolve a potentially dotted field path against the result dict.

    Returns (short_key, value).  For ``"verdict.is_funny"`` the short key is
    ``"is_funny"`` and the value is extracted from the JSON-encoded ``verdict``
    field.  For a plain key like ``"rewrite"`` it returns ``("rewrite", value)``
    with JSON strings automatically parsed into dicts.
    """
    if "." in field_path:
        parent, child = field_path.split(".", 1)
        raw = result.get(parent, "")
        if isinstance(raw, str) and raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return child, parsed.get(child, "")
            except (json.JSONDecodeError, TypeError):
                pass
        return child, ""
    val = result.get(field_path, "")
    # Parse JSON strings so structured fields become real dicts
    if isinstance(val, str) and val:
        try:
            parsed = json.loads(val)
            if isinstance(parsed, (dict, list)):
                return field_path, parsed
        except (json.JSONDecodeError, TypeError):
            pass
    return field_path, val


def filter_output(result: dict[str, Any], graph_def: GraphDef) -> tuple[str, dict[str, Any]]:
    """Select the output text and state snapshot based on output_fields config.

    Returns (output_text, state_snapshot).
    When output_fields is empty, all fields are included (backward compat).
    """
    selected = graph_def.output_fields
    _INTERNAL_KEYS = {"messages", "__interrupt__"}

    # State snapshot is always the full state (for debugging)
    state = {k: v for k, v in result.items() if k not in _INTERNAL_KEYS}

    # When nothing is selected, output all state fields
    fields_to_output = selected or [f.name for f in graph_def.state_fields]

    # Build output dict, resolving dotted sub-field paths and JSON strings
    filtered: dict[str, Any] = {}
    for field_path in fields_to_output:
        key, val = _resolve_field(result, field_path)
        if val != "":
            filtered[key] = val

    # Output text: single value unwrapped, multiple as JSON dict
    if len(filtered) == 1:
        output = str(next(iter(filtered.values())))
    elif filtered:
        output = json.dumps(filtered, indent=2, default=str)
    else:
        output = ""

    return output, state


def generate_code(graph_def: GraphDef) -> str:
    """Generate a standalone Python file that reconstructs this graph."""

    lines = [
        '"""Auto-generated LangGraph agent."""',
        "",
        "from typing import TypedDict",
        "",
        "from langgraph.graph import END, START, StateGraph",
        "",
        "",
        "class AgentState(TypedDict):",
    ]
    for sf in graph_def.state_fields:
        comment = f"  # {sf.description}" if sf.description else ""
        lines.append(f"    {sf.name}: str{comment}")
    lines.append("    messages: list")
    lines.append("")
    lines.append("")

    for node_def in graph_def.nodes:
        node_impl = get_node(node_def.type)
        fn_name = f"node_{node_def.id}"
        lines.append(f"def {fn_name}(state: dict) -> dict:")
        lines.append(f'    """Node: {node_impl.display_name} | updates: {node_def.writes_to}"""')
        lines.append(f"    config = {node_def.config!r}")
        lines.append(f"    # TODO: implement {node_impl.node_type} logic")
        lines.append(f'    state["{node_def.writes_to}"] = ""  # placeholder')
        lines.append(f"    return state")
        lines.append("")
        lines.append("")

    lines.append("def build_graph():")
    lines.append("    builder = StateGraph(AgentState)")
    lines.append("")

    for node_def in graph_def.nodes:
        lines.append(f'    builder.add_node("{node_def.id}", node_{node_def.id})')
    lines.append("")

    for edge in graph_def.edges:
        src = 'START' if edge.source == '__start__' else f'"{edge.source}"'
        tgt = 'END' if edge.target == '__end__' else f'"{edge.target}"'
        lines.append(f'    builder.add_edge({src}, {tgt})')

    lines.append("")
    lines.append("    return builder.compile()")
    lines.append("")

    return "\n".join(lines)

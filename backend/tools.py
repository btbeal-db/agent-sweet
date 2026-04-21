"""Factory that converts ToolConfig entries into LangChain BaseTool instances.

All data-access tools (Vector Search, Genie, UC Functions) are routed through
Databricks managed MCP servers.  This lets the app use OBO tokens with
``mcp.*`` scopes instead of requiring a user PAT.

MCP Server nodes use the same infrastructure directly.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
from typing import Any
from urllib.parse import urlparse

from databricks.sdk import WorkspaceClient
from databricks_mcp import DatabricksOAuthClientProvider
from langchain_core.tools import BaseTool, StructuredTool
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from .auth import get_data_client, get_user_token

logger = logging.getLogger(__name__)


# ── Managed MCP URL builders ──────────────────────────────────────────────


def _managed_mcp_url(resource_type: str, *parts: str) -> str:
    """Build a managed MCP server URL on the current workspace host."""
    host = os.environ.get("DATABRICKS_HOST", "").rstrip("/")
    if host and not host.startswith("https://"):
        host = f"https://{host}"
    return f"{host}/api/2.0/mcp/{resource_type}/{'/'.join(parts)}"


def _vs_mcp_url(index_name: str) -> str:
    """Build MCP URL for a Vector Search index (``catalog.schema.index``)."""
    parts = index_name.split(".")
    if len(parts) != 3:
        raise ValueError(f"Expected catalog.schema.index, got: {index_name}")
    return _managed_mcp_url("vector-search", *parts)


def _genie_mcp_url(room_id: str) -> str:
    """Build MCP URL for a Genie space."""
    return _managed_mcp_url("genie", room_id.strip())


def _uc_function_mcp_url(function_name: str) -> str:
    """Build MCP URL for a UC function (``catalog.schema.function``)."""
    parts = function_name.split(".")
    if len(parts) != 3:
        raise ValueError(f"Expected catalog.schema.function, got: {function_name}")
    return _managed_mcp_url("functions", *parts)


def managed_mcp_url_for_tool(tool_type: str, config: dict[str, Any]) -> str | None:
    """Return the managed MCP URL for a VS / Genie / UC Function tool config.

    Returns ``None`` if the tool type is not one of the managed types or if
    the config is missing the required field.
    """
    try:
        if tool_type == "vector_search":
            index = config.get("index_name", "")
            return _vs_mcp_url(index) if index else None
        if tool_type == "genie":
            room = config.get("room_id", "")
            return _genie_mcp_url(room) if room else None
        if tool_type == "uc_function":
            fn = config.get("function_name", "")
            return _uc_function_mcp_url(fn) if fn else None
    except ValueError:
        return None
    return None


# ── MCP helpers ───────────────────────────────────────────────────────────


def _get_mcp_client(server_url: str) -> WorkspaceClient:
    """Return a WorkspaceClient for MCP server communication.

    For managed MCP endpoints and Databricks Apps URLs the OBO token
    from the Apps proxy is preferred — these accept the ``mcp.*`` OBO
    scopes declared in ``databricks.yml``.

    Falls back to ``get_data_client()`` (PAT > OBO > SP) for everything
    else (e.g. local dev without an OBO token).
    """
    parsed = urlparse(server_url)
    if parsed.path.startswith("/api/2.0/mcp/") or parsed.netloc.endswith(".databricksapps.com"):
        obo = get_user_token()
        if obo:
            host = os.environ.get("DATABRICKS_HOST", "")
            return WorkspaceClient(host=host, token=obo, auth_type="pat")

    return get_data_client()


def _run_mcp_in_thread(fn, *args, **kwargs):
    """Run a function in a dedicated thread.

    The MCP SDK uses ``asyncio.run()`` internally, which crashes if an
    event loop is already running (e.g. inside a FastAPI handler).
    Running in a separate thread guarantees no existing event loop.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(fn, *args, **kwargs).result()


def _mcp_session(server_url: str, client: WorkspaceClient):
    """Open an authenticated MCP session via Streamable HTTP.

    Uses ``DatabricksOAuthClientProvider`` for proper OAuth auth,
    which is required by the Databricks MCP proxy (especially for
    external MCP connections).
    """
    return streamablehttp_client(
        url=server_url,
        auth=DatabricksOAuthClientProvider(client),
    )


def _mcp_list_tools(server_url: str, client: WorkspaceClient):
    """Discover tools from an MCP server."""

    async def _discover():
        async with _mcp_session(server_url, client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return (await session.list_tools()).tools

    return asyncio.run(_discover())


def _mcp_call_tool(
    server_url: str,
    client: WorkspaceClient,
    tool_name: str,
    arguments: dict,
    meta: dict[str, Any] | None = None,
):
    """Call a tool on an MCP server.

    *meta* is passed as the MCP ``_meta`` request parameter — used by
    managed MCP servers for configuration like ``num_results``,
    ``columns``, ``score_threshold``, etc.
    """

    async def _call():
        async with _mcp_session(server_url, client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.call_tool(tool_name, arguments, meta=meta)

    return asyncio.run(_call())


def _mcp_discover_and_call(
    server_url: str,
    client: WorkspaceClient,
    arguments: dict[str, Any],
    tool_name: str | None = None,
    meta: dict[str, Any] | None = None,
) -> str:
    """Discover tools and call one in a single MCP session.

    Combines discovery and invocation into a single session to avoid the
    overhead of two separate round-trips.  If *tool_name* is ``None``,
    uses the first discovered tool (suitable for managed MCP servers that
    expose exactly one tool per resource).

    *meta* is passed as the MCP ``_meta`` parameter — used by managed
    MCP servers for preset configuration (``num_results``, ``columns``,
    ``score_threshold``, etc.) that should not be LLM-generated.
    """

    async def _run():
        async with _mcp_session(server_url, client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                name = tool_name
                if name is None:
                    tools = (await session.list_tools()).tools
                    if not tools:
                        return "(no tools available on MCP server)"
                    name = tools[0].name
                result = await session.call_tool(name, arguments, meta=meta)
                parts = [c.text for c in result.content if hasattr(c, "text")]
                return "\n".join(parts) if parts else "(no output)"

    return asyncio.run(_run())


def discover_mcp_tool_metadata(
    server_url: str,
    client: WorkspaceClient | None = None,
) -> list[dict[str, Any]]:
    """Discover MCP tools and return their metadata as serializable dicts.

    Each dict contains ``name``, ``description``, and ``inputSchema`` —
    everything needed to recreate LangChain tools without re-contacting
    the MCP server.  This is called at deploy time to persist tool
    metadata in the graph artifact.

    If *client* is not provided, one is obtained via ``_get_mcp_client``.
    """
    if not server_url:
        return []

    if client is None:
        client = _get_mcp_client(server_url)

    mcp_tools = _run_mcp_in_thread(_mcp_list_tools, server_url, client)
    return [
        {
            "name": t.name,
            "description": t.description or "",
            "inputSchema": t.inputSchema,
        }
        for t in mcp_tools
    ]


# ── Tool factories ────────────────────────────────────────────────────────


def _make_mcp_tools(config: dict[str, Any]) -> list[BaseTool]:
    """Create LangChain tools from an MCP server.

    **Persisted path** (deployed models): if the config contains
    ``discovered_tools`` (a list of ``{name, description, inputSchema}``
    dicts saved at deploy time), tools are built from that metadata
    without contacting the MCP server.  This avoids runtime discovery
    failures caused by network/auth differences in the serving env.

    **Live discovery path** (preview): falls back to connecting to the
    MCP server at execution time.  Uses ``DatabricksOAuthClientProvider``
    for proper OAuth auth as required by the Databricks MCP proxy.
    """
    server_url = config.get("server_url", "")
    if not server_url:
        logger.warning("MCP tool config missing server_url")
        return []

    # ── Resolve tool metadata ───────────────────────────────────────
    # Prefer persisted metadata (injected at deploy time) so the served
    # model never needs to re-discover tools from the MCP server.
    persisted = config.get("discovered_tools")
    if persisted and isinstance(persisted, list):
        logger.info("Using %d persisted MCP tools for %s", len(persisted), server_url)
        tool_defs = persisted
    else:
        # Live discovery — retry once (cold-start on Databricks Apps).
        mcp_tools = None
        last_err: Exception | None = None
        for attempt in range(2):
            try:
                client = _get_mcp_client(server_url)
                if attempt == 0:
                    logger.info("MCP client obtained for %s (auth_type=%s)",
                                server_url, client.config.auth_type)
                mcp_tools = _run_mcp_in_thread(_mcp_list_tools, server_url, client)
                break
            except Exception as exc:
                last_err = exc
                if attempt == 0:
                    logger.warning("MCP discovery attempt 1 failed for %s, retrying: %s",
                                   server_url, exc)
        if mcp_tools is None:
            logger.error("Failed to discover MCP tools from %s after 2 attempts: %s",
                         server_url, last_err)
            return []

        logger.info("Discovered %d MCP tools from %s: %s",
                     len(mcp_tools), server_url, [t.name for t in mcp_tools])
        tool_defs = [
            {
                "name": t.name,
                "description": t.description or "",
                "inputSchema": t.inputSchema,
            }
            for t in mcp_tools
        ]

    # ── Apply tool name filter ──────────────────────────────────────
    tool_filter = config.get("tool_filter", "")
    if tool_filter and str(tool_filter).strip():
        allowed = {t.strip() for t in str(tool_filter).split(",") if t.strip()}
        tool_defs = [t for t in tool_defs if t["name"] in allowed]

    # ── Build LangChain tools ───────────────────────────────────────
    custom_desc = config.get("tool_description", "")
    tool_meta = config.get("mcp_meta")  # preset _meta params (VS config, etc.)
    sync_tools: list[BaseTool] = []

    for td in tool_defs:
        tool_name = td["name"]

        def _make_fn(_name: str = tool_name, _meta: dict | None = tool_meta) -> Any:
            def call_tool(**kwargs: Any) -> str:
                client = _get_mcp_client(server_url)  # fresh client per call
                result = _run_mcp_in_thread(
                    _mcp_call_tool, server_url, client, _name, kwargs, _meta,
                )
                parts = [c.text for c in result.content if hasattr(c, "text")]
                return "\n".join(parts) if parts else "(no output)"
            return call_tool

        desc = td.get("description", "")
        if custom_desc and len(tool_defs) == 1:
            desc = custom_desc

        sync_tools.append(
            StructuredTool(
                name=tool_name,
                description=desc,
                args_schema=td.get("inputSchema", {}),
                func=_make_fn(),
            )
        )

    return sync_tools


def _build_vs_meta(config: dict[str, Any]) -> dict[str, Any] | None:
    """Build ``_meta`` dict for VS managed MCP from node config fields.

    Maps the VS node's user-facing config to the managed MCP server's
    ``_meta`` parameters (num_results, columns, score_threshold, etc.).
    Returns ``None`` if no meta params are configured.
    """
    meta: dict[str, Any] = {}

    num_results = config.get("num_results")
    if num_results is not None and num_results != "":
        meta["num_results"] = int(num_results)

    columns = config.get("columns", "")
    if columns and str(columns).strip():
        meta["columns"] = str(columns).strip()

    score_threshold = config.get("score_threshold")
    if score_threshold is not None and score_threshold != "":
        meta["score_threshold"] = float(score_threshold)

    # Reranker: columns_to_rerank enables reranking in the MCP server
    enable_reranker = str(config.get("enable_reranker", "true")).lower() == "true"
    if enable_reranker:
        rerank_cols = config.get("columns_to_rerank", "")
        if rerank_cols and str(rerank_cols).strip():
            meta["columns_to_rerank"] = str(rerank_cols).strip()

    query_type = config.get("query_type", "")
    if query_type:
        meta["query_type"] = query_type

    return meta or None


def _make_vector_search_tool(config: dict[str, Any]) -> list[BaseTool]:
    """Create tool(s) for a Vector Search index via managed MCP."""
    index_name = config.get("index_name", "")
    if not index_name:
        logger.warning("VS tool config missing index_name")
        return []
    try:
        url = _vs_mcp_url(index_name)
    except ValueError as exc:
        logger.warning("Invalid VS index name: %s", exc)
        return []
    mcp_config: dict[str, Any] = {
        "server_url": url,
        "tool_description": config.get("tool_description", ""),
        "discovered_tools": config.get("discovered_tools"),
        "mcp_meta": _build_vs_meta(config),
    }
    return _make_mcp_tools(mcp_config)


def _make_genie_tool(config: dict[str, Any]) -> list[BaseTool]:
    """Create tool(s) for a Genie Room via managed MCP."""
    room_id = config.get("room_id", "")
    if not room_id:
        logger.warning("Genie tool config missing room_id")
        return []
    url = _genie_mcp_url(room_id)
    mcp_config = {
        "server_url": url,
        "tool_description": config.get("tool_description", ""),
        "discovered_tools": config.get("discovered_tools"),
    }
    return _make_mcp_tools(mcp_config)


def _make_uc_function_tools(config: dict[str, Any]) -> list[BaseTool]:
    """Create tool(s) for a UC Function via managed MCP."""
    function_name = config.get("function_name", "")
    if not function_name:
        logger.warning("UC function tool config missing function_name")
        return []
    try:
        url = _uc_function_mcp_url(function_name)
    except ValueError as exc:
        logger.warning("Invalid UC function name: %s", exc)
        return []
    mcp_config = {
        "server_url": url,
        "tool_description": config.get("tool_description", ""),
        "discovered_tools": config.get("discovered_tools"),
    }
    return _make_mcp_tools(mcp_config)


def make_tools(tool_configs: list[dict[str, Any]]) -> list[BaseTool]:
    """Convert a list of tool config dicts into LangChain tools.

    Each dict should have ``{"type": "...", "config": {...}}``.
    """
    tools: list[BaseTool] = []
    for tc in tool_configs:
        tool_type = tc.get("type", "")
        config = tc.get("config", {})
        if tool_type == "uc_function":
            tools.extend(_make_uc_function_tools(config))
        elif tool_type == "vector_search":
            tools.extend(_make_vector_search_tool(config))
        elif tool_type == "genie":
            tools.extend(_make_genie_tool(config))
        elif tool_type == "mcp_server":
            tools.extend(_make_mcp_tools(config))
        else:
            logger.warning("Unknown tool type: %s", tool_type)
    return tools


def make_tools_from_json(tools_json: str) -> list[BaseTool]:
    """Parse a JSON string of tool configs and return LangChain tools."""
    try:
        tool_configs = json.loads(tools_json)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Invalid tools_json: %s", tools_json[:100])
        return []
    if not isinstance(tool_configs, list):
        logger.warning("tools_json must be a JSON array, got %s", type(tool_configs))
        return []
    return make_tools(tool_configs)

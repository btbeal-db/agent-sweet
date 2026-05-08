"""Resource discovery endpoints for auto-populating node config dropdowns.

Uses the OBO token (via ``get_workspace_client()``) so results are scoped to
what the current user can see.  Every endpoint returns
``{"options": [...], "error": null}`` on success and
``{"options": [], "error": "..."}`` on failure (HTTP 200 either way) so the
frontend can degrade gracefully to manual text entry.
"""

from __future__ import annotations

import logging
import threading

from databricks_langchain import ChatDatabricks
from fastapi import APIRouter
from pydantic import BaseModel

from .auth import get_workspace_client

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Response models ──────────────────────────────────────────────────────────

class DiscoveryOption(BaseModel):
    value: str
    label: str
    description: str = ""
    provider: str | None = None  # only for serving endpoints


class DiscoveryResponse(BaseModel):
    options: list[DiscoveryOption] = []
    error: str | None = None


class EndpointCapabilities(BaseModel):
    """Capability flags for a single serving endpoint, sourced from a real
    probe call (not metadata or pattern matching). The frontend uses these
    to gate config inputs that the endpoint would reject at request time.
    """

    supports_temperature: bool = True
    error: str | None = None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _detect_provider(endpoint_name: str) -> str:
    """Map a serving endpoint name to a model provider string."""
    n = endpoint_name.lower()
    if "llama" in n or "meta" in n:
        return "meta"
    if "claude" in n or "anthropic" in n:
        return "anthropic"
    if "gpt" in n or "openai" in n or "o1-" in n or "o3-" in n:
        return "openai"
    if "mistral" in n or "mixtral" in n:
        return "mistral"
    if "dbrx" in n or "databricks" in n:
        return "databricks"
    if "gemini" in n or "google" in n:
        return "google"
    if "qwen" in n:
        return "qwen"
    return "unknown"


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/serving-endpoints", response_model=DiscoveryResponse)
def list_serving_endpoints() -> DiscoveryResponse:
    """List serving endpoints the current user can see."""
    try:
        w = get_workspace_client()
        options: list[DiscoveryOption] = []
        for ep in w.serving_endpoints.list():
            state = "Ready" if ep.state and ep.state.ready == "READY" else "Not ready"
            creator = ep.creator or ""
            desc_parts = [state]
            if creator:
                desc_parts.append(creator)
            options.append(
                DiscoveryOption(
                    value=ep.name,
                    label=ep.name,
                    description=" | ".join(desc_parts),
                    provider=_detect_provider(ep.name),
                )
            )
        return DiscoveryResponse(options=options)
    except Exception as exc:
        logger.warning("Failed to list serving endpoints: %s", exc)
        return DiscoveryResponse(error=str(exc))


# ── Capability probe ─────────────────────────────────────────────────────────

# Process-global cache. Key: endpoint name. Value: a CapabilitiesResponse-shaped
# dict. Endpoints don't change their parameter acceptance behavior over the
# lifetime of an app process, so cache entries are kept until the process
# restarts (a redeploy).
_capabilities_cache: dict[str, dict] = {}
_capabilities_cache_lock = threading.Lock()


def _probe_supports_temperature(endpoint_name: str) -> bool:
    """Return ``True`` if the named serving endpoint accepts ``temperature``.

    Sends a minimal ``temperature=0.5, max_tokens=1`` chat completion. The
    FMAPI gateway validates parameters before invoking the model, so for
    endpoints that reject ``temperature`` we get a 400 with no inference
    cost. For endpoints that accept it we pay for a single token of input
    plus a single token of output — fractions of a cent per endpoint per
    app process.

    Permissive on non-temperature errors (auth, network, rate limit, etc.) —
    if we can't tell, the LLM node's runtime call will surface the real
    failure when the user actually tries to invoke the endpoint.
    """
    try:
        ChatDatabricks(
            endpoint=endpoint_name,
            temperature=0.5,
            max_tokens=1,
        ).invoke("hi")
        return True
    except Exception as exc:
        msg = str(exc).lower()
        if "temperature" in msg and "does not support" in msg:
            return False
        logger.warning(
            "Could not probe temperature support for %s (treating as supported): %s",
            endpoint_name, exc,
        )
        return True


@router.get(
    "/serving-endpoints/{name}/capabilities", response_model=EndpointCapabilities
)
def serving_endpoint_capabilities(name: str) -> EndpointCapabilities:
    """Probe a serving endpoint to determine which parameters it accepts.

    Cached process-globally — first hit per endpoint pays the probe latency
    (~50-200ms for endpoints that 400 at validation, ~300ms-2s for endpoints
    that respond with 1 token); subsequent hits are O(1) dict lookups.
    """
    with _capabilities_cache_lock:
        cached = _capabilities_cache.get(name)
    if cached is not None:
        return EndpointCapabilities(**cached)

    supports_temperature = _probe_supports_temperature(name)
    result = {"supports_temperature": supports_temperature}
    with _capabilities_cache_lock:
        _capabilities_cache[name] = result
    return EndpointCapabilities(**result)


@router.get("/genie-spaces", response_model=DiscoveryResponse)
def list_genie_spaces() -> DiscoveryResponse:
    """List Genie spaces the current user can see."""
    try:
        w = get_workspace_client()
        result = w.genie.list_spaces()
        options: list[DiscoveryOption] = []
        for space in result.spaces or []:
            desc = (space.description or "")[:100]
            options.append(
                DiscoveryOption(
                    value=space.space_id,
                    label=space.title or space.space_id,
                    description=desc,
                )
            )
        return DiscoveryResponse(options=options)
    except Exception as exc:
        logger.warning("Failed to list Genie spaces: %s", exc)
        return DiscoveryResponse(error=str(exc))

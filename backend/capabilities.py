"""Capability detection for serving endpoints.

Used by:
  - ``discovery.py`` — populates ``DiscoveryOption.supports_temperature`` so
    the frontend can gate the temperature input when a model rejects it.
  - ``nodes/llm_node.py`` — runtime guard so a stale ``temperature`` value
    held over from a previous endpoint selection doesn't 400 the call.

Detection is metadata-aware: when an SDK ``ServingEndpoint`` object is
available we inspect each served entity's ``foundation_model.name`` /
``entity_name``, then fall back to the endpoint name.
"""

from __future__ import annotations

# Substrings (lowercased, with ``_`` normalized to ``-``) that identify
# endpoints/models known to reject the ``temperature`` parameter at the
# FMAPI layer. Extend as new reasoning endpoints land.
_NO_TEMPERATURE_PATTERNS = ("claude-opus-4-",)


def _normalize(s: str) -> str:
    return (s or "").lower().replace("_", "-")


def _matches_no_temperature(text: str) -> bool:
    return any(p in _normalize(text) for p in _NO_TEMPERATURE_PATTERNS)


def endpoint_supports_temperature(ep) -> bool:
    """Return ``True`` if a Databricks SDK serving endpoint accepts ``temperature``.

    Inspects each served entity's ``foundation_model.name`` and
    ``entity_name`` against the no-temperature patterns, then falls back
    to matching the endpoint name. Permissive default — unknown endpoints
    are assumed to support temperature.
    """
    config = getattr(ep, "config", None)
    served_entities = getattr(config, "served_entities", None) if config else None
    for entity in (served_entities or []):
        fm = getattr(entity, "foundation_model", None)
        if fm is not None and _matches_no_temperature(getattr(fm, "name", "") or ""):
            return False
        if _matches_no_temperature(getattr(entity, "entity_name", "") or ""):
            return False
    return not _matches_no_temperature(getattr(ep, "name", "") or "")


def name_likely_rejects_temperature(endpoint_name: str) -> bool:
    """Cheap fallback for callers that only have the endpoint name.

    Less reliable than ``endpoint_supports_temperature`` because it can't
    see the canonical model identifier — but it requires no SDK call, so
    it's appropriate for hot paths like runtime LLM construction.
    """
    return _matches_no_temperature(endpoint_name)

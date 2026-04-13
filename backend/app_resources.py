"""Dynamic app resource management for Databricks Apps.

Some Databricks APIs (Vector Search, Genie) lack usable OBO scopes, so queries
must run via the SP (or a user-provided PAT).  This module registers resources
on the app so the SP gets the required permissions automatically.

When a user provides a PAT, these grants are skipped — the PAT has full
permissions.  When no PAT is available, the SP acts as a proxy and needs
explicit grants to each resource the graph uses.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from .auth import get_sp_workspace_client

logger = logging.getLogger(__name__)

# In-process cache of resources already registered on the app.
# Keyed by (resource_type, identifier) so we only hit the Apps API once per resource.
_granted_resources: set[tuple[str, str]] = set()


# ── Resource granting ────────────────────────────────────────────────────────


def ensure_app_resources(graph_def: Any) -> None:
    """Register VS indexes and Genie rooms from *graph_def* as app resources.

    Skips silently in local dev (no ``DATABRICKS_APP_NAME``) or when all
    resources are already cached.
    """
    from databricks.sdk.service.apps import (
        App,
        AppResource,
        AppResourceGenieSpace,
        AppResourceGenieSpaceGenieSpacePermission,
        AppResourceUcSecurable,
        AppResourceUcSecurableUcSecurablePermission,
        AppResourceUcSecurableUcSecurableType,
    )

    app_name = os.environ.get("DATABRICKS_APP_NAME")
    if not app_name:
        return

    # Collect what the graph needs
    needed_vs: set[str] = set()
    needed_genie: set[str] = set()

    for node in graph_def.nodes:
        if node.type == "vector_search":
            idx = node.config.get("index_name", "")
            if idx:
                needed_vs.add(idx)
        elif node.type == "genie":
            rid = node.config.get("room_id", "")
            if rid:
                needed_genie.add(rid)

        # LLM tool configs can reference VS indexes and Genie rooms too
        tools_json = node.config.get("tools_json", "")
        if tools_json and str(tools_json).strip():
            try:
                for t in json.loads(str(tools_json)):
                    cfg = t.get("config", {})
                    if t.get("type") == "vector_search":
                        idx = cfg.get("index_name", "")
                        if idx:
                            needed_vs.add(idx)
                    elif t.get("type") == "genie":
                        rid = cfg.get("room_id", "")
                        if rid:
                            needed_genie.add(rid)
            except (json.JSONDecodeError, TypeError):
                pass

    needed = {("vs", v) for v in needed_vs} | {("genie", g) for g in needed_genie}
    if not needed or needed <= _granted_resources:
        return

    try:
        sp = get_sp_workspace_client()
        current_app = sp.apps.get(app_name)
        current_resources = list(current_app.resources or [])

        # Build a set of what's already registered
        existing: set[tuple[str, str]] = set()
        for r in current_resources:
            if r.uc_securable and r.uc_securable.securable_full_name:
                existing.add(("vs", r.uc_securable.securable_full_name))
            if r.genie_space and r.genie_space.space_id:
                existing.add(("genie", r.genie_space.space_id))

        missing = needed - existing - _granted_resources
        if not missing:
            _granted_resources.update(needed)
            return

        for kind, ident in missing:
            if kind == "vs":
                current_resources.append(
                    AppResource(
                        name=f"vs-{ident.replace('.', '-')}",
                        uc_securable=AppResourceUcSecurable(
                            securable_full_name=ident,
                            securable_type=AppResourceUcSecurableUcSecurableType.TABLE,
                            permission=AppResourceUcSecurableUcSecurablePermission.SELECT,
                        ),
                    )
                )
            elif kind == "genie":
                current_resources.append(
                    AppResource(
                        name=f"genie-{ident}",
                        genie_space=AppResourceGenieSpace(
                            space_id=ident,
                            name=f"genie-{ident}",
                            permission=AppResourceGenieSpaceGenieSpacePermission.CAN_RUN,
                        ),
                    )
                )

        sp.apps.update(app_name, App(name=app_name, resources=current_resources))
        _granted_resources.update(needed)
        logger.info("Registered app resources: %s", missing)
    except Exception as exc:
        logger.warning("Failed to register app resources: %s", exc)

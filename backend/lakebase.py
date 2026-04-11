"""Lakebase provisioning helpers for conversational agent checkpointing.

Provides a function to create a Lakebase Autoscaling project + database and
return the connection details needed by the serving endpoint.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.postgres import (
    Database,
    EndpointStatusState,
    Project,
    ProjectSpec,
)

logger = logging.getLogger(__name__)

# Sensible defaults for agent checkpointing workloads.
_DEFAULT_PROJECT_DISPLAY_PREFIX = "Agent Sweet"
_DEFAULT_DATABASE_ID = "checkpoints"
_DEFAULT_BRANCH = "production"
_DEFAULT_ENDPOINT = "primary"


@dataclass
class LakebaseConfig:
    """Everything a serving endpoint needs to connect to Lakebase."""

    endpoint: str  # projects/{id}/branches/{branch}/endpoints/{ep}
    host: str  # Postgres hostname
    database: str  # Postgres database name


def provision_lakebase(
    w: WorkspaceClient,
    project_id: str,
    *,
    database_id: str = _DEFAULT_DATABASE_ID,
) -> LakebaseConfig:
    """Create a Lakebase project + database and return connection details.

    Creates an Autoscaling Lakebase project with the ``production`` branch and
    ``primary`` read-write endpoint (automatic), then creates a database inside
    that branch for checkpoint storage.

    Parameters
    ----------
    w:
        Authenticated ``WorkspaceClient`` (typically PAT-based so the
        resources are owned by the deploying user).
    project_id:
        Short identifier for the project (e.g. ``"my-agent"``).  Must be
        3-63 chars, lowercase, starting with a letter.
    database_id:
        Name of the Postgres database to create.  Defaults to
        ``"checkpoints"``.

    Returns
    -------
    LakebaseConfig
        The endpoint path, host, and database name needed as env vars on
        the serving endpoint.
    """
    display_name = f"{_DEFAULT_PROJECT_DISPLAY_PREFIX} – {project_id}"

    # ── 1. Create project (auto-creates production branch + primary endpoint)
    logger.info("Creating Lakebase project %s", project_id)
    project_op = w.postgres.create_project(
        project=Project(spec=ProjectSpec(display_name=display_name)),
        project_id=project_id,
    )
    project_op.wait()
    logger.info("Project %s ready", project_id)

    # ── 2. Resolve the primary endpoint and wait for it to be ACTIVE
    branch_path = f"projects/{project_id}/branches/{_DEFAULT_BRANCH}"
    endpoint_path = f"{branch_path}/endpoints/{_DEFAULT_ENDPOINT}"

    ep = w.postgres.get_endpoint(name=endpoint_path)
    if ep.status and ep.status.current_state != EndpointStatusState.ACTIVE:
        # Poll until active (get_endpoint is cheap)
        import time

        for _ in range(60):
            time.sleep(5)
            ep = w.postgres.get_endpoint(name=endpoint_path)
            if ep.status and ep.status.current_state == EndpointStatusState.ACTIVE:
                break
        else:
            raise TimeoutError(
                f"Endpoint {endpoint_path} did not become ACTIVE within 5 minutes"
            )

    host = ep.status.hosts.host
    logger.info("Endpoint %s active at %s", endpoint_path, host)

    # ── 3. Create the checkpoints database
    logger.info("Creating database %s in %s", database_id, branch_path)
    db_op = w.postgres.create_database(
        parent=branch_path,
        database=Database(),
        database_id=database_id,
    )
    db_op.wait()
    logger.info("Database %s ready", database_id)

    return LakebaseConfig(
        endpoint=endpoint_path,
        host=host,
        database=database_id,
    )

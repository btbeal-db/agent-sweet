"""OBO (On-Behalf-Of) authentication for Databricks Apps.

When the app runs on Databricks, the user's downscoped access token is passed
in the ``x-forwarded-access-token`` request header.  We store it in a
context variable so that any code in the request path can create a
WorkspaceClient that acts on behalf of the logged-in user.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar

from databricks.sdk import WorkspaceClient

# Holds the current request's user token (set per-request by middleware)
_user_token: ContextVar[str | None] = ContextVar("_user_token", default=None)


def set_user_token(token: str | None) -> None:
    _user_token.set(token)


def get_user_token() -> str | None:
    return _user_token.get()


@contextmanager
def obo_env():
    """Context manager that sets env vars so MLflow (and other SDK clients)
    authenticate as the current OBO user instead of the app's service principal.

    Falls through as a no-op when there is no OBO token (local dev).
    """
    token = _user_token.get()
    if not token:
        yield
        return

    masked = {}
    for key in ("DATABRICKS_CLIENT_ID", "DATABRICKS_CLIENT_SECRET"):
        if key in os.environ:
            masked[key] = os.environ.pop(key)
    prev_token = os.environ.get("DATABRICKS_TOKEN")
    os.environ["DATABRICKS_TOKEN"] = token
    try:
        yield
    finally:
        if prev_token is None:
            os.environ.pop("DATABRICKS_TOKEN", None)
        else:
            os.environ["DATABRICKS_TOKEN"] = prev_token
        os.environ.update(masked)


def get_workspace_client() -> WorkspaceClient:
    """Return a WorkspaceClient using the OBO user token if available,
    otherwise fall back to the default env-var credentials (local dev).

    When an OBO token is present we temporarily mask the service principal's
    OAuth env vars so the SDK sees only one auth method (the user token).
    Do NOT pass ``auth_type`` — letting the SDK auto-detect avoids conflicts
    between legacy-scope PAT handling and OAuth M2M client-credential flows.
    """
    token = _user_token.get()
    host = os.environ.get("DATABRICKS_HOST", "")
    if token and host:
        masked = {}
        for key in ("DATABRICKS_CLIENT_ID", "DATABRICKS_CLIENT_SECRET"):
            if key in os.environ:
                masked[key] = os.environ.pop(key)
        try:
            return WorkspaceClient(host=host, token=token)
        finally:
            os.environ.update(masked)
    return WorkspaceClient()

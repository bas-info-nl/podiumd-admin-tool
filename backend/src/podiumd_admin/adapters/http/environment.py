"""``GET /api/v1/environment``: the Environment identity, without a session.

Design D5: the frontend shows the Environment banner on every page, including
the sign-in error, "no access" and error pages, so this endpoint is on the
unauthenticated allowlist. It returns the Municipality, the stage and the
optional label; the Dutch stage name is translated by the frontend.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from podiumd_admin.adapters.http.context import AppContext, app_context
from podiumd_admin.domain.environment import Stage

router = APIRouter()


class EnvironmentResponse(BaseModel):
    """The identity of the Environment this Admin Tool Instance belongs to."""

    model_config = ConfigDict(extra="forbid")

    municipality: str
    stage: Stage
    label: str | None


@router.get("/environment", operation_id="getEnvironment")
async def get_environment(
    context: Annotated[AppContext, Depends(app_context)],
) -> EnvironmentResponse:
    """The Municipality, stage and optional label of this Environment."""
    identity = context.settings.environment
    return EnvironmentResponse(
        municipality=identity.municipality, stage=identity.stage, label=identity.label
    )

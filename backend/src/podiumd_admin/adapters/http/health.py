"""Liveness and readiness (spec: installation, "Health endpoints").

Both are unauthenticated and reveal no configuration: the body is a fixed
status word. They stay out of the OpenAPI document, which is the contract with
the frontend; the platform's probes call them.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from podiumd_admin.adapters.http.context import AppContext, app_context

router = APIRouter(include_in_schema=False)


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"


@router.get("/healthz")
async def liveness() -> LivenessResponse:
    """The process runs and serves requests; never depends on the database."""
    return LivenessResponse()


@router.get("/readyz")
async def readiness(context: Annotated[AppContext, Depends(app_context)]) -> JSONResponse:
    """200 when the database is reachable, else 503; never says why."""
    try:
        ready = await context.readiness()
    except Exception:
        ready = False
    if ready:
        return JSONResponse({"status": "ready"})
    return JSONResponse({"status": "not-ready"}, status_code=503)

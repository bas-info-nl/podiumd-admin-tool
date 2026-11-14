"""Error responses the frontend shows in Dutch, chosen by their code."""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel

ACTION_NOT_RECORDED: Final = "action-not-recorded"
"""The action did not take effect because it could not be recorded in the Audit Log."""


class ErrorResponse(BaseModel):
    """An error the frontend shows in Dutch, chosen by its code."""

    error: str

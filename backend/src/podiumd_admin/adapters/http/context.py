"""What the app factory hands to the routes: the settings and the ports."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import Request

from podiumd_admin.config import Settings

if TYPE_CHECKING:
    from podiumd_admin.adapters.http.auth import AuthServices

type ReadinessCheck = Callable[[], Awaitable[bool]]


@dataclass(frozen=True, slots=True)
class AppContext:
    """The configuration and adapters one app instance runs with."""

    settings: Settings
    readiness: ReadinessCheck
    auth: AuthServices | None = None
    """The authentication use cases; ``None`` in tests that do not sign in."""


def app_context(request: Request) -> AppContext:
    """The ``AppContext`` the app factory stored on the app."""
    context = request.app.state.context
    if not isinstance(context, AppContext):  # pragma: no cover - set by create_app
        raise TypeError("the app was not built by create_app")
    return context

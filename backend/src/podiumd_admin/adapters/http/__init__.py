"""Inbound HTTP adapter: FastAPI routers, dependencies and SPA static serving."""

from podiumd_admin.adapters.http.app import create_app

__all__ = ["create_app"]

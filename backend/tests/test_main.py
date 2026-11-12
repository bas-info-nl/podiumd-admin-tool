"""The composition root that uvicorn starts (tasks 6.1, 6.2).

``create_app_from_environment`` loads the configuration, so an instance with a
missing or invalid setting fails to start, and wires the adapters into the app.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from podiumd_admin import main
from podiumd_admin.config import ConfigurationError
from tests.test_config import REQUIRED


@pytest.fixture
def environ(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    configured: list[bool] = []
    monkeypatch.setattr(main, "configure_logging", lambda: configured.append(True))
    return monkeypatch


def test_builds_the_app_from_the_environment(environ: pytest.MonkeyPatch) -> None:
    app = main.create_app_from_environment()

    with TestClient(app) as client:
        assert client.get("/api/v1/environment").json()["municipality"] == "Onsdorp"
        assert client.get("/healthz").status_code == 200


def test_fails_to_start_on_a_missing_setting(environ: pytest.MonkeyPatch) -> None:
    environ.delenv("PODIUMD_ADMIN_ENVIRONMENT_STAGE")

    with pytest.raises(ConfigurationError, match="PODIUMD_ADMIN_ENVIRONMENT_STAGE is required"):
        main.create_app_from_environment()

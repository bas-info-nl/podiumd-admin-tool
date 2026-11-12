"""Export the OpenAPI document at build time (design D2, D6).

The running app serves no OpenAPI document. The frontend generates its typed
client from the file this script writes::

    uv run podiumd-admin-openapi openapi.json

Without a path the document goes to stdout.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from fastapi.openapi.utils import get_openapi

from podiumd_admin.adapters.http.app import build_app


def openapi_document() -> dict[str, Any]:
    """The OpenAPI document of the app's routes."""
    app = build_app()
    return get_openapi(title=app.title, version=app.version, routes=app.routes)


def main(argv: Sequence[str] | None = None) -> None:
    """Write the document to the path in ``argv``, or to stdout."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    text = json.dumps(openapi_document(), indent=2, sort_keys=True) + "\n"
    if arguments:
        Path(arguments[0]).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)

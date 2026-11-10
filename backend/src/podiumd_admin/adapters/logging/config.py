"""JSON logs on stdout for ordinary application logging (ADR 0008).

structlog loggers and standard library loggers (uvicorn, SQLAlchemy, ...) go
through one handler and come out as one JSON object per line. Every ordinary
line gets ``log_type: "app"``, set last, so no caller can make an ordinary
line look like an audit line: neither by passing ``log_type="audit"``, nor by
binding it, nor through context variables.
"""

from __future__ import annotations

import logging
import sys
from typing import Final, TextIO

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

ORDINARY_LOG_TYPE: Final = "app"


def _mark_ordinary(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    event_dict["log_type"] = ORDINARY_LOG_TYPE
    return event_dict


def configure_logging(*, stream: TextIO | None = None, level: int = logging.INFO) -> None:
    """Send ordinary structlog and standard library logs to ``stream`` as JSON lines.

    ``stream`` defaults to stdout. ``level`` filters ordinary logs only; the
    ``StdoutAuditSink`` writes its lines whatever the level.
    """
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *shared,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,
                _mark_ordinary,
                structlog.processors.JSONRenderer(),
            ],
        )
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)

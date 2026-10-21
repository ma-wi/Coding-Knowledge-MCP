"""Structured logging configured for CLI and future stdio MCP safety."""

import logging
import sys
from collections.abc import MutableMapping
from typing import Any, cast

import structlog

from engineering_kb.settings import LoggingSettings


def _redactor(fields: frozenset[str]) -> structlog.types.Processor:
    def redact(
        logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
    ) -> MutableMapping[str, Any]:
        del logger, method_name
        for key in list(event_dict):
            lowered = key.lower()
            if any(field in lowered for field in fields):
                event_dict[key] = "[REDACTED]"
        return event_dict

    return redact


def configure_logging(settings: LoggingSettings) -> None:
    """Configure deterministic structured logs on stderr only."""
    level = getattr(logging, settings.level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=level, force=True)
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if settings.json_output
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redactor(frozenset(item.lower() for item in settings.redact_fields)),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(component: str) -> structlog.stdlib.BoundLogger:
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(component=component))

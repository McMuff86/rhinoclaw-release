"""
Logging configuration for RhinoClaw.

Two formats are supported:

* ``text`` (default) — human-readable, single-line, includes the
  request_id when one is attached via ``logger.<level>(msg, extra={...})``.
* ``json``           — newline-delimited JSON for log shippers.

Switch via ``RHINOCLAW_LOG_FORMAT=json``. Once a process has called
:func:`configure_logging` the root logger is set up; subsequent calls
re-apply the format and level (handy for tests).
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rhinoclaw.config import Settings


# Fields that the stdlib LogRecord always carries; everything else on the
# record dict is treated as user-supplied "extra" metadata and merged into
# the structured payload.
_STD_RECORD_FIELDS = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "asctime", "taskName",
})


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for key, value in record.__dict__.items():
            if key in _STD_RECORD_FIELDS or key.startswith("_"):
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


class _TextFormatter(logging.Formatter):
    """Human-readable formatter that surfaces the request_id when present."""

    _BASE_FMT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    def __init__(self) -> None:
        super().__init__(self._BASE_FMT)

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        request_id = getattr(record, "request_id", None)
        if request_id:
            return f"{base} [req={request_id}]"
        return base


def _build_handler(log_format: str) -> logging.Handler:
    handler = logging.StreamHandler(sys.stderr)
    if log_format == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(_TextFormatter())
    return handler


def configure_logging(settings: "Settings") -> None:
    """Configure the root logger according to ``settings``.

    Idempotent — handlers installed by previous calls are removed.
    """
    root = logging.getLogger()
    for existing in list(root.handlers):
        # Only remove handlers we installed, identified by a marker attribute.
        if getattr(existing, "_rhinoclaw_handler", False):
            root.removeHandler(existing)

    handler = _build_handler(settings.log_format)
    handler._rhinoclaw_handler = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if settings.debug else logging.INFO)

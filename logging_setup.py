# canvas_migration/logging_setup.py
from __future__ import annotations

import logging
import logging.config
from typing import Any, Mapping

class DefaultContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "course_id"):
            record.course_id = "-"
        if not hasattr(record, "artifact"):
            record.artifact = "-"
        return True

def setup_logging(verbosity: int = 1) -> None:
    """
    Configure a consistent logger for the project.
    - INFO by default, DEBUG when verbosity >= 2
    - Always prints course_id and artifact so logs are grep-able.
    """
    level = logging.DEBUG if verbosity >= 2 else logging.INFO

    fmt = (
        "%(asctime)s %(levelname)s "
        "course=%(course_id)s artifact=%(artifact)s "
        "%(message)s"
    )

    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"std": {"format": fmt}},
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "std",
                "level": level,
                "filters": ["default_context"]
            }
        },
        "loggers": {
            "canvas_migration": {"handlers": ["console"], "level": level, "propagate": False}
        },
        "filters": {
            "default_context": {
                "()": "logging_setup.DefaultContextFilter"
            }
        },
    })


class _Adapter(logging.LoggerAdapter):
    """LoggerAdapter that ensures course_id and artifact keys exist."""

    def process(self, msg: str, kwargs: Mapping[str, Any]):  # type: ignore[override]
        extra = dict(self.extra)
        # allow callers to pass extra too; we merge and prefer adapter defaults
        user_extra = kwargs.get("extra") or {}
        for k, v in user_extra.items():
            # don’t clobber required keys if adapter already set them
            if k not in extra:
                extra[k] = v
        kwargs["extra"] = extra
        return msg, kwargs


def get_logger(*, artifact: str, course_id: int) -> logging.LoggerAdapter:
    """
    Create a logger bound to artifact + course_id.
    Usage:
        log = get_logger(artifact="pages", course_id=101)
        log.info("starting export", extra={"count": 12})
    """
    base = logging.getLogger("canvas_migration")
    return _Adapter(base, extra={"artifact": artifact, "course_id": course_id})

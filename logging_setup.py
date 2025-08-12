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


# logging_setup.py
class _Adapter(logging.LoggerAdapter):
    """LoggerAdapter that ensures course_id and artifact keys exist, and avoids LogRecord collisions."""

    _RESERVED = {
        "name","msg","args","levelname","levelno","pathname","filename","module","lineno","funcName",
        "created","asctime","msecs","relativeCreated","thread","threadName","processName","process",
        "exc_info","exc_text","stack_info","stacklevel"
    }

    def process(self, msg: str, kwargs):
        extra = dict(self.extra)
        user_extra = kwargs.get("extra") or {}
        for k, v in user_extra.items():
            key = k if k not in self._RESERVED else f"meta_{k}"
            if key not in extra:  # don't clobber adapter defaults
                extra[key] = v
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

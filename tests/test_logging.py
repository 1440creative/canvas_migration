# tests/test_logging.py
import logging
import pytest
import logging_setup  # top-level module

LOGGER_NAME = "canvas_migrations"


def _attach_caplog(caplog):
    """Attach caplog.handler to our named logger (propagate=False means root won't see it)."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.addHandler(caplog.handler)
    return logger


def test_logger_includes_context_messages(caplog):
    logging_setup.setup_logging(verbosity=1)  # INFO
    log = logging_setup.get_logger(course_id=101, artifact="pages")

    logger = _attach_caplog(caplog)
    try:
        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            log.info("export started")
    finally:
        logger.removeHandler(caplog.handler)

    assert any(r.message == "export started" for r in caplog.records)
    assert any(getattr(r, "course_id", None) == 101 for r in caplog.records)
    assert any(getattr(r, "artifact", None) == "pages" for r in caplog.records)
    
    #sanity
    print(caplog)


def test_default_context_filter_unit():
    """
    Test the filter in isolation. caplog doesn't run filters on its own, so
    we construct a LogRecord and apply the filter directly.
    """
    f = logging_setup.DefaultContextFilter()
    record = logging.LogRecord(
        name=LOGGER_NAME,
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg="no extras",
        args=(),
        exc_info=None,
    )
    ok = f.filter(record)
    assert ok is True
    assert getattr(record, "course_id") == "-"
    assert getattr(record, "artifact") == "-"
    
    #sanity
    print(record)


def test_debug_level_enabled(caplog):
    logging_setup.setup_logging(verbosity=2)  # DEBUG
    log = logging_setup.get_logger(course_id=202, artifact="assignments")

    logger = _attach_caplog(caplog)
    try:
        with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
            log.debug("debugging here")
    finally:
        logger.removeHandler(caplog.handler)

    assert any(r.levelno == logging.DEBUG and r.message == "debugging here" for r in caplog.records)
    assert any(getattr(r, "course_id", None) == 202 for r in caplog.records)
    assert any(getattr(r, "artifact", None) == "assignments" for r in caplog.records)
    
    #sanity
    print(caplog)

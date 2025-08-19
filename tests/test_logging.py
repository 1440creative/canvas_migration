#tests/test_logging.py
import logging
import re
import pytest

import logging_setup

def test_logger_includes_context_messages(caplog):
    logging_setup.setup_logging(verbosity=1) #INFO level
    log = logging_setup.get_logger(course_id=101, artifact="pages")
    
    with caplog.at_level(logging.INFO, logger="canvas_migrations"):
        log.info("export started")
    
    # combine messages
    output = " ".join([r.message for r in caplog.records])
    
    # check for injected fields
    assert "export started" in output
    assert any(r.course_id == 101 for r in caplog.records)
    assert any(r.artifact == "pages" for r in caplog.records)
    
    # sanity check for me:-)
    print(caplog)

def test_default_context_filter_applies_defaults(caplog):
    logging_setup.setup_logging()
    log = logging.getLogger("canvas_migrations")
    
    with caplog.at_level(logging.INFO, logger="canvas_migrations"):
        log.info("no extras")
        
    record = caplog.records[0]
    assert hasattr(record, "course_id")
    assert record.course_id == "-"
    assert record.artifact == "-"

    # sanity
    print(record)

def test_debug_level_enabled(caplog):
    logging_setup.setup_logging(verbosity=2) # DEBUG
    log = logging_setup.get_logger(course_id=202, artifact="assignments")
    
    with caplog.at_level(logging.DEBUG, logger="canvas_migrations"):
        log.debug("debugging here")
        
    assert any("debugging here" in r.message for r in caplog.records)
    assert any(r.levelno == logging.DEBUG for r in caplog.records)
    
    #sanity
    print(caplog)
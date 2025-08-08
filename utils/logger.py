#utils/logging.py

import logging
import sys

def setup_logging(level=logging.DEBUG):
    logger = logging.getLogger("canvas_migration")
    logger.setLevel(level)
    if not logger.hasHandlers():
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            '[%(asctime)s] %(levelname)s %(name)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger

logger = setup_logging()
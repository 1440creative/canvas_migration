# tests/test_dates.py
import re
from utils import dates


def test_normalize_iso8601_with_offset():
    ts = "2025-08-19T10:52:51-07:00"
    norm = dates.normalize_iso8601(ts)
    assert norm == "2025-08-19T17:52:51Z"


def test_normalize_iso8601_already_utc():
    ts = "2025-08-19T17:52:51Z"
    norm = dates.normalize_iso8601(ts)
    assert norm == ts  # unchanged


def test_normalize_iso8601_with_fractional_seconds():
    ts = "2025-08-19T17:52:51.123Z"
    norm = dates.normalize_iso8601(ts)
    assert norm == "2025-08-19T17:52:51Z"  # microseconds stripped


def test_normalize_iso8601_none():
    assert dates.normalize_iso8601(None) is None


def test_now_utc_iso_format():
    ts = dates.now_utc_iso()
    # Regex: YYYY-MM-DDTHH:MM:SSZ
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", ts)

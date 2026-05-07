# tests/test_send_announcement.py
from __future__ import annotations

import csv
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

send_mod = importlib.import_module("scripts.send_announcement")
send_announcements = send_mod.send_announcements


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _PostTracker:
    """Canvas stub that records post() calls and returns a configurable id."""

    def __init__(self, return_ids=None):
        self._ids = list(return_ids or [101])
        self.calls = []

    def post(self, endpoint: str, **kwargs):
        self.calls.append({"endpoint": endpoint, **kwargs})
        next_id = self._ids.pop(0) if len(self._ids) > 1 else self._ids[0]

        class _Resp:
            def json(self_inner):
                return {"id": next_id}

        return _Resp()


def _make_manifest(tmp_path, rows, filename="manifest.csv"):
    f = tmp_path / filename
    with f.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["Name", "SISID", "Other"])
        writer.writeheader()
        writer.writerows(rows)
    return str(f)


# ---------------------------------------------------------------------------
# Core send_announcements() tests
# ---------------------------------------------------------------------------

def test_send_to_single_course():
    canvas = _PostTracker(return_ids=[200])
    counters = send_announcements(
        course_selectors=["sis_course_id:BAC115-ON12641"],
        title="Hello World",
        message="<p>Hi</p>",
        canvas=canvas,
    )
    assert counters == {"sent": 1, "failed": 0, "total": 1}
    assert len(canvas.calls) == 1
    call = canvas.calls[0]
    assert "/courses/sis_course_id:BAC115-ON12641/discussion_topics" in call["endpoint"]
    assert call["json"]["title"] == "Hello World"
    assert call["json"]["is_announcement"] is True
    assert call["json"]["message"] == "<p>Hi</p>"


def test_send_to_multiple_courses():
    canvas = _PostTracker(return_ids=[301, 302, 303])
    counters = send_announcements(
        course_selectors=["sis_course_id:AAA-101", "sis_course_id:BBB-202", "42"],
        title="Multi",
        message="<p>body</p>",
        canvas=canvas,
    )
    assert counters == {"sent": 3, "failed": 0, "total": 3}
    endpoints = [c["endpoint"] for c in canvas.calls]
    assert any("AAA-101" in e for e in endpoints)
    assert any("BBB-202" in e for e in endpoints)
    assert any("/courses/42/" in e for e in endpoints)


def test_numeric_selector_used_in_url():
    canvas = _PostTracker()
    send_announcements(course_selectors=["99"], title="T", message="<p>m</p>", canvas=canvas)
    assert "/courses/99/discussion_topics" in canvas.calls[0]["endpoint"]


def test_delayed_post_at_included_in_payload():
    canvas = _PostTracker()
    send_announcements(
        course_selectors=["sis_course_id:X-001"],
        title="Scheduled",
        message="<p>Later</p>",
        canvas=canvas,
        delayed_post_at="2026-09-01T09:00:00Z",
    )
    assert canvas.calls[0]["json"]["delayed_post_at"] == "2026-09-01T09:00:00Z"


def test_delayed_post_at_omitted_when_none():
    canvas = _PostTracker()
    send_announcements(
        course_selectors=["sis_course_id:X-001"],
        title="Now",
        message="<p>Immediate</p>",
        canvas=canvas,
        delayed_post_at=None,
    )
    assert "delayed_post_at" not in canvas.calls[0]["json"]


def test_dry_run_makes_no_api_calls():
    canvas = _PostTracker()
    counters = send_announcements(
        course_selectors=["sis_course_id:A", "sis_course_id:B", "sis_course_id:C"],
        title="Dry",
        message="<p>x</p>",
        canvas=canvas,
        dry_run=True,
    )
    assert counters["sent"] == 3
    assert counters["failed"] == 0
    assert len(canvas.calls) == 0


def test_failed_course_counted_separately():
    class _BrokenCanvas:
        calls = []

        def post(self, endpoint, **kwargs):
            self.calls.append(endpoint)
            raise RuntimeError("network error")

    counters = send_announcements(
        course_selectors=["sis_course_id:A", "sis_course_id:B"],
        title="Oops",
        message="<p>fail</p>",
        canvas=_BrokenCanvas(),
    )
    assert counters == {"sent": 0, "failed": 2, "total": 2}


def test_partial_failure_counted_correctly():
    call_count = 0

    class _PartialCanvas:
        def post(self, endpoint, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("timeout")

            class _Ok:
                def json(self):
                    return {"id": 999}

            return _Ok()

    counters = send_announcements(
        course_selectors=["sis_course_id:A", "sis_course_id:B"],
        title="Partial",
        message="<p>body</p>",
        canvas=_PartialCanvas(),
    )
    assert counters == {"sent": 1, "failed": 1, "total": 2}


def test_empty_course_list():
    canvas = _PostTracker()
    counters = send_announcements(
        course_selectors=[],
        title="Nobody",
        message="<p>empty</p>",
        canvas=canvas,
    )
    assert counters == {"sent": 0, "failed": 0, "total": 0}
    assert len(canvas.calls) == 0


# ---------------------------------------------------------------------------
# _load_from_manifest tests
# ---------------------------------------------------------------------------

def test_load_from_manifest_basic(tmp_path):
    path = _make_manifest(tmp_path, [
        {"Name": "Course A", "SISID": "BAC115-ON12641", "Other": "x"},
        {"Name": "Course B", "SISID": "BCPW205-ON12641", "Other": "y"},
    ])
    result = send_mod._load_from_manifest(path)
    assert result == [
        "sis_course_id:BAC115-ON12641",
        "sis_course_id:BCPW205-ON12641",
    ]


def test_load_from_manifest_skips_blank_sisid(tmp_path):
    path = _make_manifest(tmp_path, [
        {"Name": "A", "SISID": "BAC115-ON12641", "Other": ""},
        {"Name": "B", "SISID": "", "Other": ""},
        {"Name": "C", "SISID": "CHRM200-ON12641", "Other": ""},
    ])
    result = send_mod._load_from_manifest(path)
    assert result == ["sis_course_id:BAC115-ON12641", "sis_course_id:CHRM200-ON12641"]


def test_load_from_manifest_missing_column_exits(tmp_path):
    f = tmp_path / "no_sisid.csv"
    f.write_text("Name,CourseCode\nA,B\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        send_mod._load_from_manifest(str(f))
    assert exc.value.code == 2


def test_load_from_manifest_missing_file_exits(tmp_path):
    with pytest.raises(SystemExit) as exc:
        send_mod._load_from_manifest(str(tmp_path / "missing.csv"))
    assert exc.value.code == 2


def test_load_from_manifest_all_blank_sisids_exits(tmp_path):
    path = _make_manifest(tmp_path, [
        {"Name": "A", "SISID": "", "Other": ""},
        {"Name": "B", "SISID": "  ", "Other": ""},
    ])
    with pytest.raises(SystemExit) as exc:
        send_mod._load_from_manifest(path)
    assert exc.value.code == 2


def test_load_from_manifest_real_csv(tmp_path):
    """Simulate the real manifest format from the project."""
    f = tmp_path / "real.csv"
    f.write_text(
        "Flex Lead,Course Start Date,Course End Date,Canvas Start Date,SISID,Area\n"
        "Gustavo Espinola,5/2/2026,5/9/2026,4/25/2026,BAC115-ON12641,BAC\n"
        "Emily McNeill,5/4/2026,6/28/2026,4/27/2026,CHRM200-ON12641,CHRM\n",
        encoding="utf-8",
    )
    result = send_mod._load_from_manifest(str(f))
    assert result == ["sis_course_id:BAC115-ON12641", "sis_course_id:CHRM200-ON12641"]


# ---------------------------------------------------------------------------
# _load_from_ids_file tests
# ---------------------------------------------------------------------------

def test_load_from_ids_file(tmp_path):
    f = tmp_path / "ids.txt"
    f.write_text("10\n# comment\n\n20\n30\n", encoding="utf-8")
    assert send_mod._load_from_ids_file(str(f)) == ["10", "20", "30"]


def test_load_from_ids_file_bad_value_exits(tmp_path):
    f = tmp_path / "ids.txt"
    f.write_text("10\nnot-an-id\n20\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        send_mod._load_from_ids_file(str(f))
    assert exc.value.code == 2


def test_load_from_ids_file_missing_exits(tmp_path):
    with pytest.raises(SystemExit) as exc:
        send_mod._load_from_ids_file(str(tmp_path / "missing.txt"))
    assert exc.value.code == 2


def test_load_from_ids_file_empty_exits(tmp_path):
    f = tmp_path / "ids.txt"
    f.write_text("# only comments\n\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        send_mod._load_from_ids_file(str(f))
    assert exc.value.code == 2


# ---------------------------------------------------------------------------
# _load_course_selectors (argparse Namespace integration)
# ---------------------------------------------------------------------------

def _ns(**kwargs):
    import argparse
    defaults = {"manifest": None, "course_ids": None, "course_ids_file": None}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def test_load_course_selectors_from_course_ids():
    ns = _ns(course_ids=[1, 2, 3])
    assert send_mod._load_course_selectors(ns) == ["1", "2", "3"]


def test_load_course_selectors_from_ids_file(tmp_path):
    f = tmp_path / "ids.txt"
    f.write_text("10\n20\n", encoding="utf-8")
    ns = _ns(course_ids_file=str(f))
    assert send_mod._load_course_selectors(ns) == ["10", "20"]


def test_load_course_selectors_from_manifest(tmp_path):
    path = _make_manifest(tmp_path, [{"Name": "X", "SISID": "FOO-001", "Other": ""}])
    ns = _ns(manifest=path)
    assert send_mod._load_course_selectors(ns) == ["sis_course_id:FOO-001"]


# ---------------------------------------------------------------------------
# _load_message tests
# ---------------------------------------------------------------------------

def _msg_ns(**kwargs):
    import argparse
    defaults = {"message": None, "message_file": None}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def test_load_message_inline():
    ns = _msg_ns(message="<p>hello</p>")
    assert send_mod._load_message(ns) == "<p>hello</p>"


def test_load_message_from_file(tmp_path):
    f = tmp_path / "body.html"
    f.write_text("<p>from file</p>", encoding="utf-8")
    ns = _msg_ns(message_file=str(f))
    assert send_mod._load_message(ns) == "<p>from file</p>"


def test_load_message_file_missing_exits(tmp_path):
    ns = _msg_ns(message_file=str(tmp_path / "nope.html"))
    with pytest.raises(SystemExit) as exc:
        send_mod._load_message(ns)
    assert exc.value.code == 2

# tests/test_import_course_settings.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import DummyCanvas, load_importer


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


@pytest.fixture()
def import_course_settings():
    # NOTE: fully-qualified module path
    return load_importer("importers.import_course_settings", "import_course_settings")


def test_import_course_settings_puts_settings(tmp_path: Path, import_course_settings):
    export_root = tmp_path
    course_dir = export_root / "course"

    settings = {
        "default_view": "modules",
        "hide_distribution_graphs": True,
        "hide_final_grades": False,
        "restrict_student_past_view": True,
    }
    _write_json(course_dir / "settings.json", settings)
    _write_json(course_dir / "course_metadata.json", {"id": 42, "name": "Demo"})

    canvas = DummyCanvas()
    import_course_settings(
        target_course_id=123,
        export_root=export_root,
        canvas=canvas,
        queue_blueprint_sync=False,
    )

    put_calls = [c for c in canvas.calls if c["method"] == "PUT"]
    assert put_calls, "expected at least one PUT call"

    settings_call = next(
        (c for c in put_calls if f"/courses/123" in c["endpoint"] and "/settings" in c["endpoint"]),
        None,
    )
    assert settings_call is not None, f"no PUT to settings endpoint; calls={canvas.calls}"

    sent = settings_call.get("json") or {}
    for k, v in settings.items():
        assert sent.get(k) == v, f"settings key {k} not forwarded correctly"


def test_import_course_settings_updates_course_fields_when_present(tmp_path: Path, import_course_settings):
    export_root = tmp_path
    course_dir = export_root / "course"

    meta = {
        "name": "Demo",
        "course_code": "DEMO-101",
        "syllabus_body": "<p>Hello syllabus</p>",
    }
    _write_json(course_dir / "course_metadata.json", meta)

    canvas = DummyCanvas()
    import_course_settings(
        target_course_id=456,
        export_root=export_root,
        canvas=canvas,
        queue_blueprint_sync=False,
    )

    put_calls = [c for c in canvas.calls if c["method"] == "PUT"]
    course_put = next(
        (c for c in put_calls if f"/courses/456" in c["endpoint"] and "/settings" not in c["endpoint"]),
        None,
    )
    assert course_put is not None, "expected a PUT to /courses/{id} (course update)"

    payload = course_put.get("json") or {}
    assert "course" in payload and isinstance(payload["course"], dict)
    assert payload["course"].get("syllabus_body") == meta["syllabus_body"]


def test_import_course_settings_queues_blueprint_sync_when_requested(tmp_path: Path, import_course_settings):
    export_root = tmp_path
    (export_root / "course").mkdir(parents=True, exist_ok=True)

    blueprint_dir = export_root / "blueprint"
    blueprint_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        blueprint_dir / "blueprint_metadata.json",
        {
            "is_blueprint": True,
            "template": {"id": 999, "name": "Default", "default": True},
            "restrictions": {},
            "associated_courses": [1, 2, 3],
        },
    )

    canvas = DummyCanvas()
    import_course_settings(
        target_course_id=789,
        export_root=export_root,
        canvas=canvas,
        queue_blueprint_sync=True,
    )

    post_calls = [c for c in canvas.calls if c["method"] == "POST"]
    bp_post = next(
        (
            c
            for c in post_calls
            if f"/courses/789" in c["endpoint"]
            and "/blueprint_templates/" in c["endpoint"]
            and "/migrations" in c["endpoint"]
        ),
        None,
    )
    assert bp_post is not None, f"no POST to blueprint migrations endpoint; calls={canvas.calls}"

# tests/test_import_course_settings.py
import json
from pathlib import Path

from importers.import_course_settings import import_course_settings
from tests.conftest import DummyCanvas


def _write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_puts_course_fields_and_settings(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    course_dir = export_root / "course"

    meta = {
        "name": "Physics 101",
        "course_code": "PHYS101",
        "settings": {"hide_distribution_graphs": True},
    }
    _write(course_dir / "course_metadata.json", json.dumps(meta))

    api_base = "https://api.example.edu"
    canvas = DummyCanvas(api_base)

    # Two PUTs: /courses/:id and /courses/:id/settings
    put_course = requests_mock.put(
        f"{api_base}/api/v1/courses/222", json={"ok": True}, status_code=200
    )
    put_settings = requests_mock.put(
        f"{api_base}/api/v1/courses/222/settings", json={"ok": True}, status_code=200
    )

    counts = import_course_settings(
        target_course_id=222, export_root=export_root, canvas=canvas
    )

    assert counts["updated"] >= 2
    assert put_course.called
    assert put_settings.called
    body = put_course.last_request.json()
    assert "account_id" not in body.get("course", {})


def test_puts_syllabus_html(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    course_dir = export_root / "course"

    _write(course_dir / "syllabus.html", "<h1>Syllabus</h1>")

    api_base = "https://api.example.edu"
    canvas = DummyCanvas(api_base)

    # Syllabus is PUT to /courses/:id
    put_course = requests_mock.put(
        f"{api_base}/api/v1/courses/222", json={"ok": True}, status_code=200
    )

    counts = import_course_settings(
        target_course_id=222, export_root=export_root, canvas=canvas
    )

    assert counts["updated"] >= 1
    assert put_course.called


def test_sets_default_view_and_front_page(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    course_dir = export_root / "course"

    _write(
        course_dir / "home.json",
        json.dumps({"default_view": "modules", "front_page_url": "front"}),
    )

    api_base = "https://api.example.edu"
    canvas = DummyCanvas(api_base)

    put_default_view = requests_mock.put(
        f"{api_base}/api/v1/courses/222", json={"ok": True}, status_code=200
    )
    put_front_page = requests_mock.put(
        f"{api_base}/api/v1/courses/222/pages/front", json={"ok": True}, status_code=200
    )

    counts = import_course_settings(
        target_course_id=222, export_root=export_root, canvas=canvas
    )

    # Expect two updates (default_view + front_page)
    assert counts["updated"] >= 2
    assert put_default_view.called
    assert put_front_page.called


def test_blueprint_sync_optional(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"

    api_base = "https://api.example.edu"
    canvas = DummyCanvas(api_base)

    post_bp = requests_mock.post(
        f"{api_base}/api/v1/courses/222/blueprint_templates/default/migrations",
        json={"migration_id": 1},
        status_code=200,
    )

    counts = import_course_settings(
        target_course_id=222,
        export_root=export_root,
        canvas=canvas,
        queue_blueprint_sync=True,
        blueprint_sync_options={"copy_settings": True, "publish_after_migration": True},
    )

    # This call doesn't bump "updated" (we only count PUTs), but should hit the POST.
    assert isinstance(counts, dict)
    assert post_bp.called


def test_maps_course_image_with_id_map(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    course_dir = export_root / "course"

    meta = {
        "name": "Design 200",
        "image_id": 111,
    }
    _write(course_dir / "course_metadata.json", json.dumps(meta))

    api_base = "https://api.example.edu"
    canvas = DummyCanvas(api_base)

    put_course = requests_mock.put(
        f"{api_base}/api/v1/courses/333", json={"ok": True}, status_code=200
    )

    counts = import_course_settings(
        target_course_id=333,
        export_root=export_root,
        canvas=canvas,
        id_map={"files": {111: 999}},
    )

    assert counts["updated"] >= 1
    assert put_course.called
    body = put_course.last_request.json()
    assert body["course"]["image_id"] == 999
    assert body["course"]["image_url"] is None

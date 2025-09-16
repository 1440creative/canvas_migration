import json
import os
from pathlib import Path

from tests.conftest import DummyCanvas, load_importer


def _write_modules_json(root: Path, data):
    (root / "modules").mkdir(parents=True, exist_ok=True)
    (root / "modules" / "modules.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_import_modules_happy_path(tmp_path, requests_mock, monkeypatch):
    export_root = tmp_path / "export" / "data" / "123"
    # One module with three items: Page, Assignment, ExternalUrl
    mods = [
        {
            "name": "Week 1",
            "published": True,
            "items": [
                {"type": "Page", "title": "Front Page", "page_url": "front-page", "published": True},
                {"type": "Assignment", "title": "HW1", "content_id": 100, "published": True},
                {"type": "ExternalUrl", "title": "Syllabus PDF", "external_url": "https://example.org/syllabus.pdf"},
            ],
        }
    ]
    _write_modules_json(export_root, mods)

    # id_map mappings to target
    id_map = {
        "pages_url": {"front-page": "front-page"},  # page slugs usually preserved
        "assignments": {100: 200},
    }

    api_base = "https://api.example.edu"
    canvas = DummyCanvas(api_base)

    # Create module -> returns id
    requests_mock.post(
        f"{api_base}/api/v1/courses/999/modules",
        json={"id": 10, "name": "Week 1"},
        status_code=200,
    )
    # Create each item
    requests_mock.post(f"{api_base}/api/v1/courses/999/modules/10/items", json={"id": 1}, status_code=200)
    requests_mock.post(f"{api_base}/api/v1/courses/999/modules/10/items", json={"id": 2}, status_code=200)
    requests_mock.post(f"{api_base}/api/v1/courses/999/modules/10/items", json={"id": 3}, status_code=200)

    project_root = Path(os.getcwd())
    importer = load_importer(project_root, module="importers.import_modules")

    counters = importer.import_modules(
        target_course_id=999,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
    )

    assert counters["modules_created"] == 1
    assert counters["items_created"] == 3
    assert counters["items_skipped"] == 0
    assert counters["modules_failed"] == 0
    assert counters["items_failed"] == 0

    # Verify payloads roughly
    reqs = [r for r in requests_mock.request_history if r.method == "POST" and r.url.endswith("/items")]
    assert len(reqs) == 3
    # First is Page with page_url translated
    j0 = reqs[0].json()
    assert j0["module_item"]["type"] == "Page"
    assert j0["module_item"]["page_url"] == "front-page"
    assert j0["module_item"]["position"] == 1
    # Second is Assignment with mapped content_id
    j1 = reqs[1].json()
    assert j1["module_item"]["type"] == "Assignment"
    assert j1["module_item"]["content_id"] == 200
    assert j1["module_item"]["position"] == 2
    # Third is ExternalUrl
    j2 = reqs[2].json()
    assert j2["module_item"]["type"] == "ExternalUrl"
    assert j2["module_item"]["external_url"] == "https://example.org/syllabus.pdf"
    assert j2["module_item"]["position"] == 3


def test_import_modules_skips_when_mapping_missing(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "123"
    mods = [
        {
            "name": "Week 2",
            "items": [
                {"type": "Page", "title": "Overview", "page_url": "week-2-overview"},
                {"type": "Assignment", "title": "HW2", "content_id": 999},  # no map provided
            ],
        }
    ]
    _write_modules_json(export_root, mods)

    id_map = {
        # pages_url missing -> page should be skipped
        "assignments": {},  # also missing
    }

    api_base = "https://api.example.edu"
    canvas = DummyCanvas(api_base)

    requests_mock.post(
        f"{api_base}/api/v1/courses/999/modules",
        json={"id": 20, "name": "Week 2"},
        status_code=200,
    )
    # Item posts won't be called because both items should be skipped
    project_root = Path(os.getcwd())
    importer = load_importer(project_root, module="importers.import_modules")

    counters = importer.import_modules(
        target_course_id=999,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
    )

    assert counters["modules_created"] == 1
    assert counters["items_created"] == 0
    assert counters["items_skipped"] == 2
    assert counters["modules_failed"] == 0

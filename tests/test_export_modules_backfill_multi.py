# tests/test_export_modules_backfill_multi.py
from __future__ import annotations

import json
from pathlib import Path
import requests_mock

from utils.api import CanvasAPI
from export.export_pages import export_pages
from export.export_modules import export_modules
from utils.fs import ensure_dir, atomic_write, json_dumps_stable


def test_modules_backfill_pages_and_assignments(tmp_path: Path):
    course_id = 202
    root = tmp_path / "export" / "data"
    api = CanvasAPI("https://canvas.test", "tkn")

    with requests_mock.Mocker() as m:
        # --- Pages ---
        m.get(f"https://canvas.test/api/v1/courses/{course_id}/pages",
              json=[{"url": "welcome", "title": "Welcome", "page_id": 11}])
        m.get(f"https://canvas.test/api/v1/courses/{course_id}/pages/welcome",
              json={"page_id": 11, "url": "welcome", "title": "Welcome",
                    "body": "<h1>Hi</h1>", "published": True})
        export_pages(course_id, root, api)

        # --- Fake an assignment metadata written by exporter (simulate existing file) ---
        # assignments/001_essay-1/assignment_metadata.json
        assign_dir = root / str(course_id) / "assignments" / "001_essay-1"
        ensure_dir(assign_dir)
        assignment_meta = {
            "id": 555, "name": "Essay 1", "position": 1,
            "module_item_ids": [], "published": True, "updated_at": "",
        }
        atomic_write(assign_dir / "assignment_metadata.json", json_dumps_stable(assignment_meta))

        # --- Modules + items referencing both Page and Assignment ---
        m.get(f"https://canvas.test/api/v1/courses/{course_id}/modules",
              json=[{"id": 7, "name": "Week 1", "position": 1, "published": True}])
        m.get(f"https://canvas.test/api/v1/courses/{course_id}/modules/7/items",
              json=[
                  {"id": 301, "position": 1, "type": "Page", "title": "Welcome", "page_url": "welcome"},
                  {"id": 302, "position": 2, "type": "Assignment", "title": "Essay 1", "content_id": 555},
              ])
        export_modules(course_id, root, api)

    # --- Assertions ---
    page_meta_path = root / str(course_id) / "pages" / "001_welcome" / "page_metadata.json"
    page_data = json.loads(page_meta_path.read_text(encoding="utf-8"))
    assert page_data["id"] == 11
    assert page_data["module_item_ids"] == [301]

    assign_meta_path = root / str(course_id) / "assignments" / "001_essay-1" / "assignment_metadata.json"
    assign_data = json.loads(assign_meta_path.read_text(encoding="utf-8"))
    assert assign_data["id"] == 555
    assert assign_data["module_item_ids"] == [302]

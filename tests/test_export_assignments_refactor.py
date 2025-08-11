# tests/test_export_assignments_refactor.py
from __future__ import annotations
import json
from pathlib import Path
import requests_mock

from utils.api import CanvasAPI
from export.export_assignments import export_assignments

def test_export_assignments_basic(tmp_path: Path):
    course_id = 101
    root = tmp_path / "export" / "data"
    api = CanvasAPI("https://canvas.test", "tkn")

    with requests_mock.Mocker() as m:
        # list
        m.get(f"https://canvas.test/api/v1/courses/{course_id}/assignments",
              json=[{"id": 55, "name": "Essay 1", "position": 2, "published": True}])
        # detail
        m.get(f"https://canvas.test/api/v1/courses/{course_id}/assignments/55",
              json={"id": 55, "name": "Essay 1", "description": "<p>Write stuff</p>",
                    "published": True, "due_at": None, "points_possible": 100.0})

        metas = export_assignments(course_id, root, api)

    # Assertions
    a_dir = root / str(course_id) / "assignments" / "001_essay-1"
    assert (a_dir / "index.html").exists()
    meta = json.loads((a_dir / "assignment_metadata.json").read_text(encoding="utf-8"))
    assert metas[0]["id"] == 55
    assert meta["module_item_ids"] == []

# tests/test_export_discussions_refactor.py
from __future__ import annotations

import json
from pathlib import Path
import requests_mock

from utils.api import CanvasAPI
from export.export_discussions import export_discussions


def test_export_discussions_basic(tmp_path: Path):
    course_id = 606
    root = tmp_path / "export" / "data"
    api = CanvasAPI("https://canvas.test", "tkn")

    with requests_mock.Mocker() as m:
        # list
        m.get(f"https://canvas.test/api/v1/courses/{course_id}/discussion_topics",
              json=[{"id": 42, "title": "Week 1 Discussion", "position": 1}])

        # detail (includes message HTML)
        m.get(f"https://canvas.test/api/v1/courses/{course_id}/discussion_topics/42",
              json={
                  "id": 42,
                  "title": "Week 1 Discussion",
                  "message": "<p>Introduce yourself</p>",
                  "pinned": False,
                  "locked": False,
                  "require_initial_post": True,
                  "discussion_type": "threaded",
                  "posted_at": "2025-01-10T12:00:00Z",
                  "updated_at": "2025-01-11T12:00:00Z",
              })

        metas = export_discussions(course_id, root, api)

    d_dir = root / str(course_id) / "discussions" / "001_week-1-discussion"
    assert (d_dir / "index.html").exists()
    meta = json.loads((d_dir / "discussion_metadata.json").read_text(encoding="utf-8"))

    assert metas[0]["id"] == 42
    assert meta["title"] == "Week 1 Discussion"
    assert meta["module_item_ids"] == []
    assert meta["html_path"].endswith("discussions/001_week-1-discussion/index.html")
    assert meta["assignment_id"] is None

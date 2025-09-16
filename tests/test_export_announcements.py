# tests/test_export_announcements.py
from __future__ import annotations

import json
from pathlib import Path
import requests_mock

from utils.api import CanvasAPI
from export.export_announcements import export_announcements


def test_export_announcements_basic(tmp_path: Path):
    course_id = 606
    root = tmp_path / "export" / "data"
    api = CanvasAPI("https://canvas.test", "tkn")

    with requests_mock.Mocker() as m:
        # list with query params
        m.get(
            f"https://canvas.test/api/v1/courses/{course_id}/discussion_topics?only_announcements=True&per_page=100",
            json=[{"id": 99, "title": "System Announcement", "position": 1}],
        )

        # detail
        m.get(f"https://canvas.test/api/v1/courses/{course_id}/discussion_topics/99",
              json={
                  "id": 99,
                  "title": "System Announcement",
                  "message": "<p>Important notice</p>",
                  "is_announcement": True,
                  "posted_at": "2025-01-05T12:00:00Z",
                  "updated_at": "2025-01-06T12:00:00Z",
              })

        metas = export_announcements(course_id, root, api)

    a_dir = root / str(course_id) / "announcements" / "001_system-announcement"
    assert (a_dir / "index.html").exists()
    meta = json.loads((a_dir / "announcement_metadata.json").read_text(encoding="utf-8"))

    assert metas[0]["id"] == 99
    assert meta["title"] == "System Announcement"
    assert meta["html_path"].endswith("announcements/001_system-announcement/index.html")

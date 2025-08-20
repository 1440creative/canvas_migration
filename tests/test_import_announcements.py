# tests/test_import_announcements.py
from __future__ import annotations

import json
from pathlib import Path
import requests_mock

from utils.api import CanvasAPI
from importers.import_announcements import import_announcements


def test_import_announcements_basic(tmp_path: Path):
    # Setup fake export root
    export_root = tmp_path / "export" / "data" / "101"
    ann_root = export_root / "announcements" / "001_welcome"
    ann_root.mkdir(parents=True)

    # Write metadata + html
    meta = {
        "id": 42,
        "title": "Welcome!",
        "published": True,
        "html_path": "index.html",
    }
    (ann_root / "announcement_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    (ann_root / "index.html").write_text("<p>Hello students</p>", encoding="utf-8")

    api = CanvasAPI("https://canvas.test", "tkn")
    id_map: dict = {}

    with requests_mock.Mocker() as m:
        def _validate_request(request, context):
            body = json.loads(request.text)
            # ensure is_announcement flag is set
            assert body["is_announcement"] is True
            assert body["title"] == "Welcome!"
            assert "<p>Hello students</p>" in body["message"]
            return {"id": 99}

        m.post("https://canvas.test/api/v1/courses/999/discussion_topics", json=_validate_request)

        import_announcements(
            target_course_id=999,
            export_root=export_root,
            canvas=api,
            id_map=id_map,
        )

    # Verify mapping updated
    assert id_map["announcements"][42] == 99

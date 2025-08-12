from __future__ import annotations
import json
from pathlib import Path
import requests_mock

from utils.api import CanvasAPI
from export.export_settings import export_course_settings

def test_export_course_settings(tmp_path: Path):
    course_id = 777
    root = tmp_path / "export" / "data"
    api = CanvasAPI("https://canvas.test", "tkn")

    with requests_mock.Mocker() as m:
        m.get(f"https://canvas.test/api/v1/courses/{course_id}",
              json={"id": course_id, "uuid": "abc", "name": "Demo", "course_code": "DEMO",
                    "enrollment_term_id": 55, "account_id": 1, "workflow_state": "available",
                    "start_at": None, "end_at": None, "blueprint": False})
        m.get(f"https://canvas.test/api/v1/courses/{course_id}/settings",
              json={"allow_student_forum_attachments": True, "blueprint": False})

        info = export_course_settings(course_id, root, api)

    assert info["is_blueprint"] is False
    md = json.loads((root / str(course_id) / "course" / "course_metadata.json").read_text("utf-8"))
    st = json.loads((root / str(course_id) / "course" / "course_settings.json").read_text("utf-8"))
    assert md["id"] == course_id
    assert st["allow_student_forum_attachments"] is True

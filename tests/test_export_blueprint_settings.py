from __future__ import annotations
import json
from pathlib import Path
import requests_mock

from utils.api import CanvasAPI
from export.export_blueprint_settings import export_blueprint_settings

def test_export_blueprint_settings(tmp_path: Path):
    course_id = 888
    root = tmp_path / "export" / "data"
    api = CanvasAPI("https://canvas.test", "tkn")

    with requests_mock.Mocker() as m:
        # settings say it's blueprint
        m.get(f"https://canvas.test/api/v1/courses/{course_id}/settings",
              json={"blueprint": True})

        # list templates (with default)
        m.get(f"https://canvas.test/api/v1/courses/{course_id}/blueprint_templates",
              json=[{"id": 9, "name": "Default", "default": True}])

        # template detail
        m.get(f"https://canvas.test/api/v1/courses/{course_id}/blueprint_templates/9",
              json={"id": 9, "name": "Default", "default": True})

        # restrictions (optional)
        m.get(f"https://canvas.test/api/v1/courses/{course_id}/blueprint_templates/9/restrictions",
              json={"content": {"quizzes": True, "pages": True}})

        # associated courses (optional)
        m.get(f"https://canvas.test/api/v1/courses/{course_id}/blueprint_templates/9/associated_courses",
              json=[{"id": 1}, {"id": 2}])

        meta = export_blueprint_settings(course_id, root, api)

    bp = json.loads((root / str(course_id) / "blueprint" / "blueprint_metadata.json").read_text("utf-8"))
    assert meta["template"]["id"] == 9
    assert bp["is_blueprint"] is True
    assert bp["template"]["default"] is True
    assert bp["associated_courses"] == [1, 2]

def test_non_blueprint_skips(tmp_path: Path):
    course_id = 889
    root = tmp_path / "export" / "data"
    api = CanvasAPI("https://canvas.test", "tkn")

    with requests_mock.Mocker() as m:
        m.get(f"https://canvas.test/api/v1/courses/{course_id}/settings", json={"blueprint": False})
        meta = export_blueprint_settings(course_id, root, api)

    # no blueprint dir written
    assert meta == {}
    assert not (root / str(course_id) / "blueprint").exists()

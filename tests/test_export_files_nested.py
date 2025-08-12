# tests/test_export_files_nested.py
from __future__ import annotations

import json
from pathlib import Path
import requests_mock

from utils.api import CanvasAPI
from export.export_files import export_files

def test_nested_folders(tmp_path: Path):
    course_id = 909
    root = tmp_path / "export" / "data"
    api = CanvasAPI("https://canvas.test", "tkn")

    with requests_mock.Mocker() as m:
        # Folder hierarchy: course files/Unit 1/Week A/Images
        m.get(f"https://canvas.test/api/v1/courses/{course_id}/folders", json=[
            {"id": 100, "full_name": "course files"},
            {"id": 110, "full_name": "course files/Unit 1"},
            {"id": 120, "full_name": "course files/Unit 1/Week A"},
            {"id": 130, "full_name": "course files/Unit 1/Week A/Images"},
        ])

        # File in the deepest folder
        m.get(f"https://canvas.test/api/v1/courses/{course_id}/files", json=[
            {"id": 5001, "filename": "diagram.png", "content-type": "image/png", "folder_id": 130,
             "url": "https://canvas.test/files/5001/download"}
        ])

        m.get("https://canvas.test/files/5001/download", content=b"\x89PNG\r\n\x1a\nnested\n")

        metas = export_files(course_id, root, api)

    course_root = root / str(course_id)
    saved = course_root / "files" / "unit-1" / "week-a" / "images" / "diagram.png"
    sidecar = saved.parent / "diagram.png.metadata.json"

    assert saved.exists()
    assert sidecar.exists()
    data = json.loads(sidecar.read_text("utf-8"))
    assert data["file_path"].endswith("files/unit-1/week-a/images/diagram.png")
    assert metas and metas[0]["id"] == 5001

# tests/test_export_modules_backfill_files_sidecar.py
from __future__ import annotations
import json
from pathlib import Path
import requests_mock

from utils.api import CanvasAPI
from export.export_modules import export_modules

def test_modules_backfill_file_sidecars(tmp_path: Path):
    course_id = 4242
    root = tmp_path / "export" / "data"
    course_root = root / str(course_id)
    files_dir = course_root / "files" / "unit-1"
    files_dir.mkdir(parents=True, exist_ok=True)

    # Write a sidecar that matches file id 9001
    sidecar = files_dir / "diagram.png.metadata.json"
    sidecar.write_text(json.dumps({
        "id": 9001,
        "filename": "diagram.png",
        "file_path": "files/unit-1/diagram.png",
        "module_item_ids": []
    }), encoding="utf-8")

    api = CanvasAPI("https://canvas.test", "tkn")

    with requests_mock.Mocker() as m:
        # One module with one File item pointing at content_id=9001
        m.get(f"https://canvas.test/api/v1/courses/{course_id}/modules",
              json=[{"id": 1, "name": "Week 1", "position": 1, "published": True}])
        m.get(f"https://canvas.test/api/v1/courses/{course_id}/modules/1/items",
              json=[{"id": 777, "position": 1, "type": "File", "title": "Diagram", "content_id": 9001}])

        export_modules(course_id, root, api)

    # Sidecar should be backfilled with module_item_ids [777]
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert data["module_item_ids"] == [777]

# tests/test_export_files_refactor.py
from __future__ import annotations

import json
from pathlib import Path
import requests_mock

from utils.api import CanvasAPI
from export.export_files import export_files


def test_export_files_basic(tmp_path: Path):
    course_id = 505
    root = tmp_path / "export" / "data"
    api = CanvasAPI("https://canvas.test", "tkn")

    with requests_mock.Mocker() as m:
        # Folders map: root and "Course Files/Syllabus"
        m.get(f"https://canvas.test/api/v1/courses/{course_id}/folders", json=[
            {"id": 10, "full_name": "course files"},  # root
            {"id": 11, "full_name": "course files/Syllabus"},
        ])

        # Files list: one PDF in Syllabus
        m.get(f"https://canvas.test/api/v1/courses/{course_id}/files", json=[
            {"id": 3001, "filename": "syllabus.pdf", "content-type": "application/pdf", "folder_id": 11,
             "url": f"https://canvas.test/files/3001/download"}
        ])

        # Binary download
        pdf_bytes = b"%PDF-1.4\n%deterministic\n"
        m.get("https://canvas.test/files/3001/download", content=pdf_bytes)

        metas = export_files(course_id, root, api)

    # Assert paths and metadata
    course_root = root / str(course_id)
    saved = course_root / "files" / "syllabus" / "syllabus.pdf"  # "Syllabus" -> "syllabus" by sanitize_slug
    sidecar = saved.parent / "syllabus.pdf.metadata.json"

    assert saved.exists(), f"expected file at {saved}"
    assert sidecar.exists(), "expected sidecar metadata"

    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert data["id"] == 3001
    assert data["filename"] == "syllabus.pdf"
    assert data["content_type"] == "application/pdf"
    assert data["file_path"].endswith("files/syllabus/syllabus.pdf")
    assert isinstance(data["sha256"], str) and len(data["sha256"]) == 64
    assert data["module_item_ids"] == []

    # metas return list mirrors sidecar data basics
    assert metas and metas[0]["id"] == 3001

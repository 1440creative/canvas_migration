import json
import os
from pathlib import Path
import importlib.util

import pytest
import requests

from tests.conftest import DummyCanvas


def load_importer(project_root: Path):
    mod_path = (project_root / "importers" / "import_pages.py").resolve()
    assert mod_path.exists(), f"Expected module at {mod_path}, but it does not exist."

    spec = importlib.util.spec_from_file_location("import_pages_mod", str(mod_path))
    assert spec and spec.loader, f"Could not build spec for {mod_path}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    exported = dir(mod)
    assert hasattr(mod, "import_pages"), (
        f"'import_pages' not found in {mod_path}.\n"
        f"Exported names:\n{exported}"
    )
    return mod


def test_import_pages_basic(tmp_path, requests_mock):
    # --- Arrange export tree
    export_root = tmp_path / "export" / "data" / "101"
    page_dir = export_root / "pages" / "welcome-old"
    page_dir.mkdir(parents=True)

    meta = {
        "id": 987,
        "url": "welcome-old",
        "title": "Welcome",
        "published": True,
        "position": 1,
        "front_page": False,
        "html_path": "index.html",
    }
    (page_dir / "page_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    (page_dir / "index.html").write_text("<h2>Hi</h2><p>Welcome!</p>", encoding="utf-8")

    # --- Arrange API mocks
    api_base = "https://api.example.edu"  # pretend Canvas API host
    create_url = f"{api_base}/api/v1/courses/222/pages"

    # POST create returns slug + id directly
    requests_mock.post(
        create_url,
        json={"url": "welcome", "id": 123, "position": 3},
        status_code=200,
    )

    canvas = DummyCanvas(api_base)
    project_root = Path(os.getcwd())
    importer = load_importer(project_root)

    id_map = {}

    # --- Act
    counters = importer.import_pages(
        target_course_id=222,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
    )

    # --- Assert
    assert counters["imported"] == 1
    assert id_map["pages"] == {987: 123}
    assert id_map["pages_url"] == {"welcome-old": "welcome"}


def test_import_pages_location_follow(tmp_path, requests_mock):
    # --- Arrange export tree
    export_root = tmp_path / "export" / "data" / "101"
    page_dir = export_root / "pages" / "syllabus-old"
    page_dir.mkdir(parents=True)

    meta = {
        "id": 321,
        "url": "syllabus-old",
        "title": "Syllabus",
        "published": False,
        "position": 2,
    }
    (page_dir / "page_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    (page_dir / "index.html").write_text("<p>Course overview</p>", encoding="utf-8")

    # --- Arrange API mocks
    api_base = "https://api.example.edu"
    create_url = f"{api_base}/api/v1/courses/222/pages"
    follow_url = f"{api_base}/api/v1/courses/222/pages/syllabus"

    # POST returns only slug and a Location header for canonical fetch (no id in JSON)
    requests_mock.post(
        create_url,
        json={"url": "syllabus"},
        status_code=201,
        headers={"Location": follow_url},
    )

    # GET follow returns full page object with id (and maybe position)
    requests_mock.get(
        follow_url,
        json={"url": "syllabus", "id": 654, "position": 2},
        status_code=200,
    )

    canvas = DummyCanvas(api_base)
    project_root = Path(os.getcwd())
    importer = load_importer(project_root)

    id_map = {}

    # --- Act
    counters = importer.import_pages(
        target_course_id=222,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
    )

    # --- Assert
    assert counters["imported"] == 1
    assert id_map["pages"] == {321: 654}
    assert id_map["pages_url"] == {"syllabus-old": "syllabus"}

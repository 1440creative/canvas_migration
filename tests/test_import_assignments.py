# tests/test_import_assignments.py
import json
import importlib.util
from pathlib import Path
import requests


def _load_assignments_module(project_root: Path):
    mod_path = (project_root /"importers"/ "import_assignments.py").resolve()
    assert mod_path.exists(), f"Expected module at {mod_path}"
    spec = importlib.util.spec_from_file_location("import_assignments_mod", str(mod_path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader, f"Could not build spec for {mod_path}"
    spec.loader.exec_module(mod)
    assert hasattr(mod, "import_assignments") and callable(mod.import_assignments), \
        "import_assignments not found or not callable"
    return mod


class DummyCanvas:
    def __init__(self, api_base: str):
        self.api_root = api_base.rstrip("/") + "/"
        self.session = requests.Session()

    def _full(self, ep: str) -> str:
        ep = (ep or "").strip()
        if ep.startswith("/api/v1"):
            ep = ep[len("/api/v1"):]
        return self.api_root + "api/v1/" + ep.lstrip("/")

    def post(self, endpoint: str, **kwargs):
        return self.session.post(self._full(endpoint), **kwargs)

    def put(self, endpoint: str, **kwargs):
        return self.session.put(self._full(endpoint), **kwargs)

    def post_json(self, endpoint: str, *, payload: dict) -> dict:
        r = self.post(endpoint, json=payload); r.raise_for_status(); return r.json()


def test_import_assignments_basic(tmp_path, requests_mock):
    # Build export tree
    export_root = tmp_path / "export" / "data" / "101"
    a_dir = export_root / "assignments" / "hw1"
    a_dir.mkdir(parents=True)
    (a_dir / "description.html").write_text("<p>Read Chapter 1</p>", encoding="utf-8")
    (a_dir / "assignment_metadata.json").write_text(json.dumps({
        "id": 555,
        "name": "Homework 1",
        "points_possible": 10,
        "published": True,
        "submission_types": ["online_text_entry", "online_upload"],
        "allowed_extensions": ["pdf", "docx"],
        "due_at": "2025-09-01T23:59:00Z",
    }), encoding="utf-8")

    api_base = "https://api.example.edu"
    requests_mock.post(
        f"{api_base}/api/v1/courses/222/assignments",
        json={"id": 999, "name": "Homework 1"},
        status_code=200,
    )

    canvas = DummyCanvas(api_base)
    mod = _load_assignments_module(Path.cwd())

    id_map = {}
    mod.import_assignments(
        target_course_id=222,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
    )

    assert id_map["assignments"] == {555: 999}


def test_import_assignments_missing_name_skips(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    a_dir = export_root / "assignments" / "no-name"
    a_dir.mkdir(parents=True)
    (a_dir / "assignment_metadata.json").write_text(json.dumps({
        "id": 42,
        "points_possible": 5
    }), encoding="utf-8")

    api_base = "https://api.example.edu"
    canvas = DummyCanvas(api_base)
    mod = _load_assignments_module(Path.cwd())

    id_map = {}
    mod.import_assignments(
        target_course_id=333,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
    )

    # No POST should have been made; nothing mapped
    assert "assignments" not in id_map or id_map["assignments"] == {}

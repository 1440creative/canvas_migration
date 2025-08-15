# tests/test_import_discussions.py
import json
import importlib.util
from pathlib import Path
import requests


def _load_discussions_module(project_root: Path):
    mod_path = (project_root / "importers" / "import_discussions.py").resolve()
    assert mod_path.exists(), f"Expected module at {mod_path}"
    spec = importlib.util.spec_from_file_location("import_discussions_mod", str(mod_path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader, f"Could not build spec for {mod_path}"
    spec.loader.exec_module(mod)
    assert hasattr(mod, "import_discussions") and callable(mod.import_discussions), \
        "import_discussions not found or not callable"
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


def test_import_discussions_basic(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    ddir = export_root / "discussions" / "welcome-thread"
    ddir.mkdir(parents=True)
    (ddir / "discussion_metadata.json").write_text(json.dumps({
        "id": 600,
        "title": "Welcome Thread",
        "published": True,
        "message": "This will be overridden by HTML file"
    }), encoding="utf-8")
    (ddir / "description.html").write_text("<p>Welcome HTML</p>", encoding="utf-8")

    api_base = "https://api.example.edu"
    requests_mock.post(f"{api_base}/api/v1/courses/222/discussion_topics",
                       json={"id": 8800, "title": "Welcome Thread"}, status_code=200)

    canvas = DummyCanvas(api_base)
    mod = _load_discussions_module(Path.cwd())
    id_map = {}

    mod.import_discussions(
        target_course_id=222,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
    )

    assert id_map["discussions"] == {600: 8800}


def test_import_discussions_missing_title_skips(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    ddir = export_root / "discussions" / "no-title"
    ddir.mkdir(parents=True)
    (ddir / "discussion_metadata.json").write_text(json.dumps({
        "id": 601,
        "published": True
    }), encoding="utf-8")

    api_base = "https://api.example.edu"
    canvas = DummyCanvas(api_base)
    mod = _load_discussions_module(Path.cwd())
    id_map = {}

    mod.import_discussions(
        target_course_id=333,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
    )

    assert "discussions" not in id_map or id_map["discussions"] == {}

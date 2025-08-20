import json
import importlib.util
import logging
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


# ---------------------------------------------------------------------------

def test_import_discussions_basic(tmp_path, requests_mock, caplog):
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

    with caplog.at_level(logging.INFO):
        mod.import_discussions(
            target_course_id=222,
            export_root=export_root,
            canvas=canvas,
            id_map=id_map,
        )

    assert id_map["discussions"] == {600: 8800}
    summary = "\n".join(r.message for r in caplog.records if "Discussions import complete" in r.message)
    assert "imported=1" in summary
    assert "skipped=0" in summary
    assert "failed=0" in summary
    assert "total=1" in summary


def test_import_discussions_missing_title_skips(tmp_path, requests_mock, caplog):
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

    with caplog.at_level(logging.INFO):
        mod.import_discussions(
            target_course_id=333,
            export_root=export_root,
            canvas=canvas,
            id_map=id_map,
        )

    assert "discussions" not in id_map or id_map["discussions"] == {}
    summary = "\n".join(r.message for r in caplog.records if "Discussions import complete" in r.message)
    assert "imported=0" in summary
    assert "skipped=1" in summary
    assert "failed=0" in summary
    assert "total=1" in summary


def test_import_discussions_uses_allowed_fields(tmp_path, requests_mock, caplog):
    export_root = tmp_path / "export" / "data" / "101"
    ddir = export_root / "discussions" / "allowed"
    ddir.mkdir(parents=True)
    (ddir / "discussion_metadata.json").write_text(json.dumps({
        "id": 700,
        "title": "Allowed Fields Only",
        "published": True,
        "bogus_field": "SHOULD NOT BE SENT"
    }), encoding="utf-8")

    api_base = "https://api.example.edu"
    seen_payload = {}
    def _callback(req, ctx):
        seen_payload.update(req.json())
        return {"id": 9900}
    requests_mock.post(f"{api_base}/api/v1/courses/444/discussion_topics", json=_callback)

    canvas = DummyCanvas(api_base)
    mod = _load_discussions_module(Path.cwd())
    id_map = {}

    with caplog.at_level(logging.INFO):
        mod.import_discussions(
            target_course_id=444,
            export_root=export_root,
            canvas=canvas,
            id_map=id_map,
        )

    assert 700 in id_map["discussions"]
    assert "bogus_field" not in seen_payload


def test_import_discussions_description_html_overrides(tmp_path, requests_mock, caplog):
    export_root = tmp_path / "export" / "data" / "101"
    ddir = export_root / "discussions" / "html-overrides"
    ddir.mkdir(parents=True)
    (ddir / "discussion_metadata.json").write_text(json.dumps({
        "id": 701,
        "title": "HTML Override",
        "published": True,
        "message": "Fallback message"
    }), encoding="utf-8")
    (ddir / "description.html").write_text("<p>Override HTML</p>", encoding="utf-8")

    api_base = "https://api.example.edu"
    seen_payload = {}
    def _callback(req, ctx):
        seen_payload.update(req.json())
        return {"id": 9901}
    requests_mock.post(f"{api_base}/api/v1/courses/555/discussion_topics", json=_callback)

    canvas = DummyCanvas(api_base)
    mod = _load_discussions_module(Path.cwd())
    id_map = {}

    with caplog.at_level(logging.INFO):
        mod.import_discussions(
            target_course_id=555,
            export_root=export_root,
            canvas=canvas,
            id_map=id_map,
        )

    assert "Override HTML" in seen_payload["message"]


def test_import_discussions_handles_graded_discussion(tmp_path, requests_mock, caplog):
    export_root = tmp_path / "export" / "data" / "101"
    ddir = export_root / "discussions" / "graded"
    ddir.mkdir(parents=True)
    (ddir / "discussion_metadata.json").write_text(json.dumps({
        "id": 702,
        "title": "Graded Disc",
        "assignment": {
            "points_possible": 10,
            "grading_type": "points",
            "bogus": "ignore me"
        }
    }), encoding="utf-8")

    api_base = "https://api.example.edu"
    seen_payload = {}
    def _callback(req, ctx):
        seen_payload.update(req.json())
        return {"id": 9902}
    requests_mock.post(f"{api_base}/api/v1/courses/666/discussion_topics", json=_callback)

    canvas = DummyCanvas(api_base)
    mod = _load_discussions_module(Path.cwd())
    id_map = {}

    with caplog.at_level(logging.INFO):
        mod.import_discussions(
            target_course_id=666,
            export_root=export_root,
            canvas=canvas,
            id_map=id_map,
        )

    assert "assignment" in seen_payload
    assert "points_possible" in seen_payload["assignment"]
    assert "bogus" not in seen_payload["assignment"]


def test_import_discussions_error_increments_failed(tmp_path, requests_mock, caplog):
    export_root = tmp_path / "export" / "data" / "101"
    ddir = export_root / "discussions" / "bad"
    ddir.mkdir(parents=True)
    (ddir / "discussion_metadata.json").write_text(json.dumps({
        "id": 703,
        "title": "Will Fail"
    }), encoding="utf-8")

    api_base = "https://api.example.edu"
    requests_mock.post(f"{api_base}/api/v1/courses/777/discussion_topics",
                       status_code=500, json={"error": "fail"})

    canvas = DummyCanvas(api_base)
    mod = _load_discussions_module(Path.cwd())
    id_map = {}

    with caplog.at_level(logging.INFO):
        mod.import_discussions(
            target_course_id=777,
            export_root=export_root,
            canvas=canvas,
            id_map=id_map,
        )

    summary = "\n".join(r.message for r in caplog.records if "Discussions import complete" in r.message)
    assert "failed=1" in summary

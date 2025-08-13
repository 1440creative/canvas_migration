# tests/test_import_pages.py
import json
import importlib.util
from pathlib import Path
import requests


# ---- Loader (load import/import_pages.py by path since "import" is a keyword dir)
def _load_pages_module(project_root: Path):
    mod_path = (project_root / "import" / "import_pages.py").resolve()
    assert mod_path.exists(), f"Expected module at {mod_path}"
    spec = importlib.util.spec_from_file_location("import_pages_mod", str(mod_path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader, f"Could not build spec for {mod_path}"
    spec.loader.exec_module(mod)
    assert hasattr(mod, "import_pages") and callable(mod.import_pages), \
        "import_pages not found or not callable"
    return mod


# ---- Minimal Canvas-like wrapper that plays well with requests_mock
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
        r = self.post(endpoint, json=payload)
        r.raise_for_status()
        return r.json()


def test_import_pages_happy_path(tmp_path, requests_mock):
    """
    Creates a page and marks it as front page.
    Canvas returns both url and page_id; we expect both id and slug maps to be recorded.
    """
    export_root = tmp_path / "export" / "data" / "101"
    page_dir = export_root / "pages" / "welcome"
    page_dir.mkdir(parents=True)
    (page_dir / "index.html").write_text("<h1>Hello</h1>", encoding="utf-8")
    (page_dir / "page_metadata.json").write_text(json.dumps({
        "id": 42,
        "title": "Welcome",
        "url": "welcome-old",
        "published": True,
        "front_page": True
    }), encoding="utf-8")

    api_base = "https://api.example.edu"
    # POST create page
    requests_mock.post(
        f"{api_base}/api/v1/courses/222/pages",
        json={"url": "welcome", "page_id": 314},
        status_code=200,
    )
    # PUT mark front page
    requests_mock.put(
        f"{api_base}/api/v1/courses/222/pages/welcome",
        json={"url": "welcome", "page_id": 314, "front_page": True},
        status_code=200,
    )

    canvas = DummyCanvas(api_base)
    mod = _load_pages_module(Path.cwd())

    id_map = {}
    mod.import_pages(
        target_course_id=222,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
    )

    assert id_map["pages"] == {42: 314}
    assert id_map["pages_url"] == {"welcome-old": "welcome"}


def test_import_pages_slug_only_response(tmp_path, requests_mock):
    """
    Canvas returns only a slug (no numeric id). We still record pages_url mapping.
    """
    export_root = tmp_path / "export" / "data" / "101"
    page_dir = export_root / "pages" / "faq"
    page_dir.mkdir(parents=True)
    # Use alternate body filename to exercise fallback search
    (page_dir / "body.html").write_text("<p>FAQ</p>", encoding="utf-8")
    (page_dir / "page_metadata.json").write_text(json.dumps({
        "id": 7,
        "title": "FAQ",
        "url": "faq-old",
        "published": False,
        "front_page": False
    }), encoding="utf-8")

    api_base = "https://api.example.edu"
    # POST create page returns only slug
    requests_mock.post(
        f"{api_base}/api/v1/courses/333/pages",
        json={"url": "faq"},
        status_code=200,
    )

    canvas = DummyCanvas(api_base)
    mod = _load_pages_module(Path.cwd())

    id_map = {}
    mod.import_pages(
        target_course_id=333,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
    )

    # We must have slug mapping; id mapping may be absent if Canvas didn't return a numeric id
    assert id_map["pages_url"] == {"faq-old": "faq"}
    # If pages map exists, it should not contain 7
    if "pages" in id_map:
        assert 7 not in id_map["pages"]

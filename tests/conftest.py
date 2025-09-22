# tests/conftest.py
from __future__ import annotations

import json
import importlib
import sys
from pathlib import Path

import pytest
import requests


# ---------- lightweight response used by record-only calls ----------
class DummyResponse:
    def __init__(self, status_code: int = 200, json_data=None, headers=None):
        self.status_code = status_code
        self._json = json_data
        self.headers = headers or {}
        self.text = json.dumps(json_data) if json_data is not None else ""

    def json(self):
        if self._json is None:
            raise ValueError("No JSON on this DummyResponse")
        return self._json

    def raise_for_status(self):
        if not (200 <= self.status_code < 400):
            raise requests.HTTPError(f"{self.status_code} error")


# ---------- the Canvas test double ----------
class DummyCanvas:
    """
    Dual-mode test client:

    - For most endpoints (get/post/put/delete), we RECORD calls and return a DummyResponse.
      This avoids outbound HTTP for settings/blueprint tests and lets you assert on canvas.calls.

    - For file uploads, importers call:
        1) begin_course_file_upload(...) -> returns presigned upload_url (no HTTP)
        2) _multipart_post(upload_url, ...) -> uses a real requests.Session.post so requests_mock intercepts

      If the upload host returns a 302 Location to a Canvas finalize URL, the importer calls
      self.session.get(...), which requests_mock will also intercept.
    """
    def __init__(self, api_base: str = "https://api.test", upload_url: str = "https://uploads.test/upload"):
        base = api_base.rstrip("/")
        self.api_base = base
        self.api_root = base
        self.upload_url = upload_url

        # call recording (used by many tests)
        self.calls = []
        self.get_calls = []
        self.post_calls = []
        self.put_calls = []
        self.delete_calls = []

        # a real session so requests_mock sees outbound calls to upload/finalize hosts
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": "Bearer TEST",
            "Content-Type": "application/json"
        })

    # ----- helpers -----
    def _url(self, endpoint: str) -> str:
        if not endpoint:
            return self.api_base
        ep = str(endpoint).strip()
        if ep.startswith("http://") or ep.startswith("https://"):
            return ep
        if ep.startswith("/api/v1/"):
            pass
        elif ep.startswith("api/v1/"):
            ep = "/" + ep
        elif ep.startswith("courses/"):
            ep = "/api/v1/" + ep
        elif not ep.startswith("/"):
            ep = "/" + ep
        return self.api_base + ep

    def _record(self, method: str, endpoint: str, **kwargs):
        call = {"method": method.upper(), "endpoint": endpoint}
        if "json" in kwargs:
            call["json"] = kwargs["json"]
        self.calls.append(call)
        if method.upper() == "GET":
            self.get_calls.append(call)
        elif method.upper() == "POST":
            self.post_calls.append(call)
        elif method.upper() == "PUT":
            self.put_calls.append(call)
        elif method.upper() == "DELETE":
            self.delete_calls.append(call)

    # ----- record-only CRUD (no network) -----
    def get(self, endpoint: str, **kwargs):
        self._record("GET", endpoint, **kwargs)
        return DummyResponse(200, json_data={})

    def post(self, endpoint: str, **kwargs):
        self._record("POST", endpoint, **kwargs)
        return DummyResponse(200, json_data={})

    def put(self, endpoint: str, **kwargs):
        self._record("PUT", endpoint, **kwargs)
        return DummyResponse(200, json_data={})

    def delete(self, endpoint: str, **kwargs):
        self._record("DELETE", endpoint, **kwargs)
        return DummyResponse(200, json_data={})

    # ----- file-upload flow bits -----
    def begin_course_file_upload(
        self,
        course_id: int,
        *,
        name: str,
        parent_folder_path: str,
        on_duplicate: str = "overwrite",
    ) -> dict:
        # Record a synthetic handshake for visibility; do NOT perform HTTP.
        self._record(
            "POST",
            f"/api/v1/courses/{course_id}/files",
            json={
                "name": name,
                "parent_folder_path": parent_folder_path,
                "on_duplicate": on_duplicate,
            },
        )
        # Hand back the presigned upload target the tests stub with requests_mock
        return {"upload_url": self.upload_url, "upload_params": {}}

    def _multipart_post(self, url: str, *, data: dict, files: dict) -> requests.Response:
        # Use the real session so requests_mock intercepts this call.
        headers = self.session.headers.copy()
        headers.pop("Content-Type", None)  # let requests set multipart boundary
        return self.session.post(url, data=data, files=files, headers=headers)


# ---------- import helpers ----------
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_importer(module_path=None, func_name=None, **kwargs):
    """
    Flexible test helper:
      - load_importer("importers.import_discussions", "import_discussions") -> returns function
      - load_importer(module="importers.import_discussions", func="import_discussions") -> returns function
      - load_importer(module="importers.import_discussions") -> returns module
      - load_importer(func_name="import_announcements") -> returns module importers.import_announcements
      - load_importer(Path.cwd()) (legacy) -> returns module importers.import_announcements
    """
    import importlib
    from pathlib import Path

    # Accept keyword aliases used in some tests
    module_path = kwargs.get("module", module_path)
    func_name = kwargs.get("func", kwargs.get("function", func_name))

    # Legacy: tests pass just Path.cwd() and expect the announcements module
    if isinstance(module_path, Path) or (module_path is None and not func_name and kwargs.get("project_root")):
        return importlib.import_module("importers.import_announcements")

    # If both provided, return the function
    if module_path and func_name:
        mod = importlib.import_module(module_path)
        return getattr(mod, func_name)

    # If only module provided, return the module
    if module_path and not func_name:
        return importlib.import_module(module_path)

    # If only func provided, assume importers.<func> is a module and return it
    if func_name and not module_path:
        return importlib.import_module(f"importers.{func_name}")

    raise TypeError("load_importer requires a module and/or function (see docstring for accepted forms).")



# ---------- common fixtures ----------
@pytest.fixture
def dummy_canvas():
    # api_base aligns with finalize URLs in tests; upload_url with uploads host in tests
    return DummyCanvas(api_base="https://api.test", upload_url="https://uploads.test/upload")


@pytest.fixture
def id_map():
    return {"files": {}}


@pytest.fixture
def tmp_export(tmp_path: Path):
    root = tmp_path / "export" / "data" / "101"
    (root / "files").mkdir(parents=True, exist_ok=True)
    return root

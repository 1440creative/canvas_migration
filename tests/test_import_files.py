import json
import os
from pathlib import Path
import importlib.util

import pytest
import requests


def load_importer(project_root: Path):
    mod_path = (project_root /"importers"/ "import_files.py").resolve()
    assert mod_path.exists(), f"Expected module at {mod_path}, but it does not exist."

    spec = importlib.util.spec_from_file_location("import_files_mod", str(mod_path))
    assert spec and spec.loader, f"Could not build spec for {mod_path}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Strong assertion with helpful context
    exported = dir(mod)
    assert hasattr(mod, "import_files"), (
        f"'import_files' not found in {mod_path}.\n"
        f"Exported names:\n{exported}"
    )
    return mod

class DummyCanvas:
    """
    Minimal Canvas-like wrapper that matches your utils/api.CanvasAPI surface.
    Uses a real requests.Session so requests_mock can intercept calls.
    """
    def __init__(self, api_base: str):
        self.api_root = api_base.rstrip("/") + "/"
        self.session = requests.Session()

    # methods the importer expects
    def post(self, path: str, **kwargs):
        url = self._full_url(path)
        return self.session.post(url, **kwargs)

    def post_json(self, endpoint: str, *, payload: dict) -> dict:
        r = self.post(endpoint, json=payload)
        r.raise_for_status()
        return r.json()

    def begin_course_file_upload(self, course_id: int, *, name: str,
                                 parent_folder_path: str, on_duplicate: str = "overwrite") -> dict:
        payload = {
            "name": name,
            "parent_folder_path": parent_folder_path,
            "on_duplicate": on_duplicate,
        }
        return self.post_json(f"/api/v1/courses/{course_id}/files", payload=payload)

    # tiny URL joiner compatible with your utils/api._full_url behavior
    def _full_url(self, endpoint: str) -> str:
        ep = (endpoint or "").strip()
        if ep.startswith("/api/v1"):
            ep = ep[len("/api/v1"):]
        ep = ep.lstrip("/")
        return self.api_root + "api/v1/" + ep


def test_import_files_upload_flow(tmp_path, requests_mock):
    # --- Arrange: build a fake export tree
    export_root = tmp_path / "export" / "data" / "101"
    files_dir = export_root / "files" / "foo"
    files_dir.mkdir(parents=True)

    # Create a file + matching metadata
    file_path = files_dir / "hello.txt"
    file_path.write_text("hello world", encoding="utf-8")
    meta = {
        "id": 111,
        "file_name": "hello.txt",
        "folder_path": "foo",  # explicit; importer also supports deriving from layout
    }
    (files_dir / "hello.txt.metadata.json").write_text(json.dumps(meta), encoding="utf-8")

    # --- Arrange: mock Canvas API + upload host endpoints
    api_base = "https://api.example.edu"  # pretend Canvas API host
    upload_host = "https://upload.example.com"  # the presigned upload host

    handshake_url = f"{api_base}/api/v1/courses/222/files"
    upload_url = f"{upload_host}/upload"
    finalize_url = f"{api_base}/finalize/abc123"

    # Step 1: POST handshake to API returns upload_url + upload_params
    requests_mock.post(
        handshake_url,
        json={"upload_url": upload_url, "upload_params": {"key": "value"}},
        status_code=200,
    )

    # Step 2: POST to upload_url returns a redirect to finalize
    requests_mock.post(
        upload_url,
        status_code=302,
        headers={"Location": finalize_url},
    )

    # Step 3: GET finalize returns the new file object with an id
    requests_mock.get(finalize_url, json={"id": 123}, status_code=200)

    # Build our dummy canvas client (uses a real Session so requests_mock intercepts)
    canvas = DummyCanvas(api_base)

    # Dynamically load the importer module from path
    project_root = Path(os.getcwd())  # adjust if your tests run from repo root
    importer = load_importer(project_root)

    id_map = {}

    # --- Act
    importer.import_files(
        target_course_id=222,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
        on_duplicate="overwrite",
        verbosity=0,
    )

    # --- Assert
    assert "files" in id_map
    assert id_map["files"] == {111: 123}

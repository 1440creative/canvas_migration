import json
import os
from pathlib import Path
import importlib.util

import pytest
import requests

from tests.conftest import DummyCanvas



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

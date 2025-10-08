# tests/test_import_files.py
import json
from pathlib import Path
import pytest

from importers.import_files import import_files, _manifest_path
from tests.conftest import DummyCanvas

# ---------- Local fixtures (self-contained) ----------
@pytest.fixture
def tmp_export(tmp_path):
    root = tmp_path / "export" / "data" / "101"
    (root / "files").mkdir(parents=True, exist_ok=True)
    return root

@pytest.fixture
def id_map():
    return {}

@pytest.fixture
def dummy_canvas(requests_mock):
    # Use the same base across tests
    api_base = "https://api.test"
    c = DummyCanvas(api_base)

    # Handshake stub: Canvas init upload returns uploads host
    requests_mock.post(
        f"{api_base}/api/v1/courses/101/files",
        json={"upload_url": "https://uploads.test/upload", "upload_params": {}},
        status_code=200,
    )
    return c

# ---------- Helpers ----------
def _write_exported_file(tmp_export, rel_path: str, *, file_id: int, file_name: str, folder_path: str | None = None, content=b"hi"):
    p = tmp_export / "files" / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    meta = {
        "id": file_id,
        "file_name": file_name,
    }
    if folder_path is not None:
        meta["folder_path"] = folder_path
    (p.parent / f"{file_name}.metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    return p

# ---------- Tests ----------
def test_upload_basic_updates_id_map(tmp_export, id_map, requests_mock, dummy_canvas):
    _ = _write_exported_file(tmp_export, "sub/inner/a.txt", file_id=42, file_name="a.txt", folder_path=None, content=b"hello")

    # Upload host returns final JSON with the file id
    requests_mock.post("https://uploads.test/upload", json={"id": 9001}, status_code=200)

    import_files(
        target_course_id=101,
        export_root=tmp_export,
        canvas=dummy_canvas,
        id_map=id_map,
        on_duplicate="overwrite",
    )

    assert id_map["files"][42] == 9001
    man = json.loads(_manifest_path(tmp_export).read_text(encoding="utf-8"))
    entry = man["sub/inner/a.txt"]
    assert entry["new_id"] == 9001
    assert entry["target_course_id"] == 101

def test_upload_handles_redirect_finalize(tmp_export, id_map, requests_mock, dummy_canvas):
    _ = _write_exported_file(tmp_export, "only/a.txt", file_id=7, file_name="a.txt", folder_path=None, content=b"abc")

    # Upload host returns a 302 to Canvas finalize URL
    requests_mock.post(
        "https://uploads.test/upload",
        status_code=302,
        headers={"Location": "https://api.test/api/v1/files/finalize/123"},
    )
    # Finalize GET returns nested attachment payload
    requests_mock.get("https://api.test/api/v1/files/finalize/123", json={"attachment": {"id": 777}}, status_code=200)

    import_files(target_course_id=101, export_root=tmp_export, canvas=dummy_canvas, id_map=id_map)
    assert id_map["files"][7] == 777

def test_manifest_skip_counts_as_skipped(tmp_export, id_map, requests_mock, dummy_canvas, caplog):
    _ = _write_exported_file(tmp_export, "dup/a.txt", file_id=99, file_name="a.txt", content=b"xyz")
    requests_mock.post("https://uploads.test/upload", json={"id": 5000}, status_code=200)

    # First run → uploads the file
    import_files(target_course_id=101, export_root=tmp_export, canvas=dummy_canvas, id_map=id_map)

    # Second run → no HTTP expected; skipped via manifest
    requests_mock.reset_mock()
    caplog.set_level("INFO")
    import_files(target_course_id=101, export_root=tmp_export, canvas=dummy_canvas, id_map=id_map)

    msgs = [r.getMessage().lower() for r in caplog.records]
    assert any("skipped upload (same sha256)" in m for m in msgs), msgs


def test_manifest_skip_requires_matching_course(tmp_export, id_map, requests_mock, dummy_canvas):
    _ = _write_exported_file(tmp_export, "dup/a.txt", file_id=1, file_name="a.txt", content=b"xyz")
    requests_mock.post("https://uploads.test/upload", json={"id": 5000}, status_code=200)

    # Initial upload to course 101
    import_files(target_course_id=101, export_root=tmp_export, canvas=dummy_canvas, id_map=id_map)

    # Change course; expect a second upload because manifest course id differs
    requests_mock.post("https://uploads.test/upload", json={"id": 6000}, status_code=200)
    id_map.clear()
    import_files(target_course_id=202, export_root=tmp_export, canvas=dummy_canvas, id_map=id_map)

    assert id_map["files"][1] == 6000
    man = json.loads(_manifest_path(tmp_export).read_text(encoding="utf-8"))
    assert man["dup/a.txt"]["target_course_id"] == 202

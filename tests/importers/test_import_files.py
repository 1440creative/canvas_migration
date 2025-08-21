# tests/importers/test_import_files.py
import json
from pathlib import Path
from importers.import_files import import_files, _manifest_path

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

def test_upload_basic_updates_id_map(tmp_export, id_map, requests_mock, dummy_canvas):
    # seed one file without explicit folder_path; should derive from rel path
    p = _write_exported_file(tmp_export, "sub/inner/a.txt", file_id=42, file_name="a.txt", folder_path=None, content=b"hello")
    # stub upload host to return final JSON with file id
    requests_mock.post("https://uploads.test/upload", json={"id": 9001}, status_code=200)

    import_files(
        target_course_id=101,
        export_root=tmp_export,
        canvas=dummy_canvas,
        id_map=id_map,
        on_duplicate="overwrite",
    )

    assert id_map["files"][42] == 9001  # int keys ok if you keep them as ints
    # manifest should be written and include the sha + new_id
    man = json.loads(_manifest_path(tmp_export).read_text(encoding="utf-8"))
    assert "sub/inner/a.txt" in man
    assert man["sub/inner/a.txt"]["new_id"] == 9001

def test_upload_handles_redirect_finalize(tmp_export, id_map, requests_mock, dummy_canvas):
    p = _write_exported_file(tmp_export, "only/a.txt", file_id=7, file_name="a.txt", folder_path=None, content=b"abc")
    # first POST to uploads host returns 302 to Canvas finalize URL
    requests_mock.post("https://uploads.test/upload",
                       status_code=302,
                       headers={"Location": "https://api.test/api/v1/files/finalize/123"})
    # finalize GET returns attachment payload
    requests_mock.get("https://api.test/api/v1/files/finalize/123", json={"attachment": {"id": 777}}, status_code=200)

    import_files(
        target_course_id=101,
        export_root=tmp_export,
        canvas=dummy_canvas,
        id_map=id_map,
    )
    assert id_map["files"][7] == 777

def test_manifest_skip_counts_as_skipped(tmp_export, id_map, requests_mock, dummy_canvas, caplog):
    # seed and first import
    p = _write_exported_file(tmp_export, "dup/a.txt", file_id=99, file_name="a.txt", content=b"xyz")
    requests_mock.post("https://uploads.test/upload", json={"id": 5000}, status_code=200)

    import_files(target_course_id=101, export_root=tmp_export, canvas=dummy_canvas, id_map=id_map)

    # run again with no content change → should skip via manifest and not call uploads host
    requests_mock.reset_mock()  # ensure no HTTP is attempted on second run
    caplog.set_level("INFO")    # capture INFO logs


    import_files(target_course_id=101, export_root=tmp_export, canvas=dummy_canvas, id_map=id_map)

    # assert skip message present
    msgs = [r.getMessage().lower() for r in caplog.records]
    assert any("skipped upload (same sha256)" in m for m in msgs), msgs

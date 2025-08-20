import json
from pathlib import Path

from importers import import_pages
from tests.test_import_pages import DummyCanvas  # reuse your helper


def test_front_page_put_failure_increments_failed(tmp_path, requests_mock, caplog):
    export_root = tmp_path / "export" / "data" / "101"
    page_dir = export_root / "pages" / "home"
    page_dir.mkdir(parents=True)
    (page_dir / "index.html").write_text("<h1>Home</h1>", encoding="utf-8")
    (page_dir / "page_metadata.json").write_text(json.dumps({
        "id": 55,
        "title": "Home",
        "url": "home-old",
        "published": True,
        "front_page": True
    }), encoding="utf-8")

    api_base = "https://api.example.edu"
    # POST create page succeeds
    requests_mock.post(
        f"{api_base}/api/v1/courses/999/pages",
        json={"url": "home", "page_id": 123},
        status_code=200,
    )
    # PUT mark front page fails with 500
    requests_mock.put(
        f"{api_base}/api/v1/courses/999/pages/home",
        status_code=500,
    )

    canvas = DummyCanvas(api_base)
    id_map = {}

    caplog.set_level("INFO")

    import_pages.import_pages(
        target_course_id=999,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
    )

    # Mapping should still be recorded
    assert id_map["pages"][55] == 123
    assert id_map["pages_url"]["home-old"] == "home"

    # Logs should include error about front page
    assert any("Failed to set front page" in r.message for r in caplog.records)

    # Final summary log should show 1 imported, 0 skipped, 1 failed, 2 total
    summary = caplog.messages[-1]
    assert "imported=1" in summary
    assert "skipped=0" in summary
    assert "failed=1" in summary
    assert "total=2" in summary
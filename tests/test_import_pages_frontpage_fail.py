import json
import logging
from pathlib import Path

import pytest

import importers.import_pages as import_pages

from tests.conftest import DummyCanvas




def test_front_page_put_failure_increments_failed(tmp_path: Path, requests_mock, caplog: pytest.LogCaptureFixture):
    # Arrange: export root with one front page
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
    # POST succeeds
    requests_mock.post(
        f"{api_base}/api/v1/courses/999/pages",
        json={"url": "home", "page_id": 123},
        status_code=200,
    )
    # PUT to set front page fails
    requests_mock.put(
        f"{api_base}/api/v1/courses/999/pages/home",
        status_code=500,
    )

    canvas = DummyCanvas(api_base)
    id_map = {}

    caplog.set_level(logging.INFO)

    # Act
    counters = import_pages.import_pages(
        target_course_id=999,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
    )

    # Assert
    assert counters["imported"] == 1
    assert counters["failed"] == 1  # front_page failure counted
    assert "failed-frontpage" in caplog.text

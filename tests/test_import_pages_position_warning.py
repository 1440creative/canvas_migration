import json
import logging
from pathlib import Path

import pytest

import importers.import_pages as import_pages
from tests.conftest import DummyCanvas


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_logs_position_warning_once(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    export_root = tmp_path / "export" / "data" / "101"
    for i in (1, 2):
        page_dir = export_root / "pages" / f"00{i}_page-{i}"
        _write(page_dir / "index.html", f"<h1>P{i}</h1>")
        _write(
            page_dir / "page_metadata.json",
            json.dumps({
                "id": i,
                "title": f"P{i}",
                "url": f"p{i}-old",
                "published": True,
                "position": i,
            })
        )

    # Reset warning guard
    import_pages._WARNED_PAGE_POSITION = False

    proj_logger = logging.getLogger("canvas_migrations")
    prev_propagate = proj_logger.propagate
    proj_logger.propagate = True
    try:
        caplog.set_level(logging.DEBUG, logger="canvas_migrations")

        canvas = DummyCanvas()
        id_map = {}

        counters = import_pages.import_pages(
            target_course_id=222,
            export_root=export_root,
            canvas=canvas,
            id_map=id_map,
        )
    finally:
        proj_logger.propagate = prev_propagate

    # Assert
    assert counters["imported"] == 2
    assert "position-field-ignored" in caplog.text
    # Ensure warning fired only once
    assert caplog.text.count("position-field-ignored") == 1

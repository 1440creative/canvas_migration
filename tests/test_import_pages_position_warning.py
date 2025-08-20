# tests/test_import_pages_position_warning.py
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
import requests

import logging_setup
from importers.import_pages import import_pages


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class DummyCanvas:
    """
    Minimal Canvas-like client that satisfies the Protocol used by import_pages.
    It returns predictable page IDs and slugs, and uses a real requests.Session
    so requests-mock (if used elsewhere) can intercept.
    """
    def __init__(self):
        self.api_root = "https://example.test/api/v1/"
        self.session = requests.Session()
        self._next_id = 100

    def post(self, endpoint: str, **kwargs):
        # Not used directly by this importer (it calls post_json)
        raise NotImplementedError

    def put(self, endpoint: str, **kwargs):
        # For _set_front_page: just return a dummy 200-like object
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"ok": True}
        return R()

    def post_json(self, endpoint: str, *, payload: dict) -> dict:
        # Simulate Canvas create page response. Always return a slug + page_id.
        self._next_id += 1
        page_id = self._next_id
        title = payload.get("wiki_page", {}).get("title", f"p{page_id}")
        # Make slugs deterministic from the page_id
        return {"url": f"p{page_id}", "page_id": page_id, "title": title}


@pytest.fixture(autouse=True)
def setup_project_logging():
    # Ensure project logger is configured for tests
    logging_setup.setup_logging(verbosity=2)  # DEBUG
    yield


def test_logs_position_warning_once(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    # Arrange: minimal export tree with two pages, both including 'position'
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
                "position": i,  # <- field we want to warn about
            })
        )

    # Reset the module-level guard so the warning can fire in this test
    import importers.import_pages as import_pages_mod
    import_pages_mod._WARNED_PAGE_POSITION = False

    # Enable propagation so pytest's caplog handler can see our project logs
    proj_logger = logging.getLogger("canvas_migrations")
    prev_propagate = proj_logger.propagate
    proj_logger.propagate = True
    try:
        # Capture DEBUG and above for our project logger
        caplog.set_level(logging.DEBUG, logger="canvas_migrations")

        canvas = DummyCanvas()
        id_map = {}

        # Act: run importer once
        import_pages(
            target_course_id=222,
            export_root=export_root,
            canvas=canvas,
            id_map=id_map,
        )

        # Assert: exactly one message about ignoring PageMeta.position
        text = caplog.text
        assert text.count("Ignoring PageMeta.position") == 1, text

        # Bonus: running again should NOT log the warning (guard stays True)
        import_pages(
            target_course_id=222,
            export_root=export_root,
            canvas=canvas,
            id_map=id_map,
        )
        text2 = caplog.text
        # Still only one total
        assert text2.count("Ignoring PageMeta.position") == 1, text2
    finally:
        proj_logger.propagate = prev_propagate

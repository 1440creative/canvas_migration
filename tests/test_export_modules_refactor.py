# tests/test_export_modules_refactor.py
from pathlib import Path
import json
import requests_mock

from utils.api import CanvasAPI
from export.export_pages import export_pages
from export.export_modules import export_modules

def test_modules_backfill_pages(tmp_path: Path):
    course_id = 101
    root = tmp_path / "export" / "data"
    api = CanvasAPI("https://canvas.test", "tkn")

    with requests_mock.Mocker() as m:
        # Pages
        m.get(f"https://canvas.test/api/v1/courses/{course_id}/pages",
              json=[{"url": "welcome", "title": "Welcome", "page_id": 1}])
        m.get(f"https://canvas.test/api/v1/courses/{course_id}/pages/welcome",
              json={"page_id": 1, "url": "welcome", "title": "Welcome",
                    "body": "<h1>Hi</h1>", "published": True})

        export_pages(course_id, root, api)

        # Modules + items
        m.get(f"https://canvas.test/api/v1/courses/{course_id}/modules",
              json=[{"id": 7, "name": "Week 1", "position": 1, "published": True}])
        m.get(f"https://canvas.test/api/v1/courses/{course_id}/modules/7/items",
              json=[{"id": 301, "position": 1, "type": "Page", "title": "Welcome", "page_url": "welcome", "indent": 2}])

        export_modules(course_id, root, api)

    meta_path = root / "101/pages/001_welcome/page_metadata.json"
    data = json.loads(meta_path.read_text(encoding="utf-8"))

    # Assert module_item_ids were backfilled
    assert data["module_item_ids"] == [301]

    # Bonus sanity checks
    assert data["id"] == 1
    assert data["url"] == "welcome"
    assert data["html_path"].endswith("pages/001_welcome/index.html")

    modules_path = root / "101/modules/modules.json"
    modules = json.loads(modules_path.read_text(encoding="utf-8"))
    assert modules[0]["items"][0]["indent"] == 2

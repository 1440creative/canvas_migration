#tests/test_import_modules.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

# SUT
from importers.import_modules import import_modules


class DummyCanvasAPI:
    """
    Minimal stub of utils.api.CanvasAPI used for unit tests.
    Records JSON POSTs and returns deterministic ids.
    """
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self._next_id = 1000

    def post_json(self, url: str, **kwargs) -> Dict[str, Any]:
        json = kwargs.get('payload', kwargs.get('json'))
        self.calls.append({"url": url, "json": json})
        # Modules endpoint returns a new module id.
        if url.endswith("/modules"):
            self._next_id += 1
            return {"id": self._next_id, "name": json["module"]["name"]}
        # Items endpoint returns a new item id.
        if "/modules/" in url and url.endswith("/items"):
            self._next_id += 1
            return {"id": self._next_id}
        # Default
        return {}


@pytest.fixture()
def export_root(tmp_path: Path) -> Path:
    """
    Creates:
      export/data/123/modules/modules.json
    """
    root = tmp_path / "export" / "data" / "123"
    modules_dir = root / "modules"
    modules_dir.mkdir(parents=True, exist_ok=True)

    modules = [
        {
            "id": 11,
            "name": "Week 1",
            "position": 1,
            "published": True,
            "require_sequential_progress": False,
            "items": [
                {"id": 1, "type": "SubHeader", "title": "Readings", "position": 1},
                {"id": 2, "type": "Page", "title": "Intro Page", "position": 2, "page_url": "intro"},
                {"id": 3, "type": "Assignment", "title": "HW 1", "position": 3, "content_id": 201},
                {"id": 4, "type": "ExternalUrl", "title": "Syllabus link", "position": 4, "external_url": "https://example.edu/syllabus"},
                {"id": 5, "type": "Quiz", "title": "Quiz 1", "position": 5, "content_id": 301},
                {"id": 6, "type": "File", "title": "Slides", "position": 6, "content_id": 401},
                {"id": 7, "type": "Discussion", "title": "Week 1 Discussion", "position": 7, "content_id": 501},
                {"id": 8, "type": "ExternalTool", "title": "LTI Thing", "position": 8, "external_tool_url": "https://lti.example.com/launch", "new_tab": True},
            ],
        }
    ]

    (modules_dir / "modules.json").write_text(json.dumps(modules, indent=2))
    return root


def test_import_modules_happy_path(export_root: Path) -> None:
    canvas = DummyCanvasAPI()
    id_map: Dict[str, Dict[Any, Any]] = {
        "files": {401: 1401},
        "pages": {},
        "pages_url": {"intro": "intro-new"},
        "assignments": {201: 1201},
        "quizzes": {301: 1301},
        "discussions": {501: 1501},
    }

    target_course_id = 999

    import_modules(
        target_course_id=target_course_id,
        export_root=export_root,
        canvas=canvas,  # dummy
        id_map=id_map,
    )

    # Modules mapping recorded
    assert "modules" in id_map
    # First module created by DummyCanvasAPI gets id 1001 (starts at 1000, then +1)
    assert id_map["modules"][11] == 1001

    # First call: create module
    assert canvas.calls[0]["url"] == f"/courses/{target_course_id}/modules"
    mod_payload = canvas.calls[0]["json"]["module"]
    assert mod_payload["name"] == "Week 1"
    assert mod_payload["position"] == 1
    assert mod_payload["published"] is True
    assert mod_payload["require_sequential_progress"] is False

    # Subsequent calls: module items, all to .../modules/1001/items
    item_calls = canvas.calls[1:]
    assert all(c["url"] == f"/courses/{target_course_id}/modules/1001/items" for c in item_calls)

    # Check a few representative payloads
    # SubHeader (id=1)
    subheader = item_calls[0]["json"]["module_item"]
    assert subheader["type"] == "SubHeader"
    assert subheader["title"] == "Readings"

    # Page (id=2) maps slug
    page_item = item_calls[1]["json"]["module_item"]
    assert page_item["type"] == "Page"
    assert page_item["page_url"] == "intro-new"

    # Assignment (id=3) uses mapped content_id
    asg_item = item_calls[2]["json"]["module_item"]
    assert asg_item["type"] == "Assignment"
    assert asg_item["content_id"] == 1201

    # ExternalUrl retains external_url + title
    ext_url_item = item_calls[3]["json"]["module_item"]
    assert ext_url_item["type"] == "ExternalUrl"
    assert ext_url_item["external_url"] == "https://example.edu/syllabus"
    assert ext_url_item["title"] == "Syllabus link"

    # Quiz mapping
    quiz_item = item_calls[4]["json"]["module_item"]
    assert quiz_item["type"] == "Quiz"
    assert quiz_item["content_id"] == 1301

    # File mapping
    file_item = item_calls[5]["json"]["module_item"]
    assert file_item["type"] == "File"
    assert file_item["content_id"] == 1401

    # Discussion mapping
    disc_item = item_calls[6]["json"]["module_item"]
    assert disc_item["type"] == "Discussion"
    assert disc_item["content_id"] == 1501

    # ExternalTool
    tool_item = item_calls[7]["json"]["module_item"]
    assert tool_item["type"] == "ExternalTool"
    assert tool_item["external_tool_url"] == "https://lti.example.com/launch"
    assert tool_item["new_tab"] is True


def test_import_modules_skips_missing_mappings(export_root: Path) -> None:
    """
    If a required mapping is missing (e.g., Page slug), we skip that item rather than failing.
    """
    canvas = DummyCanvasAPI()
    id_map: Dict[str, Dict[Any, Any]] = {
        "files": {},
        "pages": {},
        "pages_url": {},  # <-- missing page slug mapping
        "assignments": {201: 1201},
        "quizzes": {301: 1301},
        "discussions": {501: 1501},
    }

    import_modules(
        target_course_id=999,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
    )

    # Module still created
    assert id_map["modules"][11] == 1001

    # Ensure a Page item was NOT posted (because slug mapping was missing).
    payloads = [c["json"]["module_item"] for c in canvas.calls[1:]]  # skip the module create call
    page_posts = [p for p in payloads if p["type"] == "Page"]
    assert page_posts == []

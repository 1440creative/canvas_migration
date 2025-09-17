# tests/test_export_modules_pagination.py
from export.export_modules import export_modules
from utils.api import CanvasAPI

def test_export_modules_pagination(tmp_path, requests_mock):
    course_id = 303
    base_api = "https://canvas.test/api/v1"

    # Page 1 of modules (with lowercase 'link' header for next)
    requests_mock.get(
        f"{base_api}/courses/{course_id}/modules",
        json=[{"id": 1, "name": "Module 1", "position": 1}],
        # headers={"Link": f'<{base_api}/courses/{course_id}/modules?page=2>; rel="next"'}
        headers={"link": f'<{base_api}/courses/{course_id}/modules?page=2>; rel="next"'}

    )

    # Page 2 of modules (no Link header -> end of pagination)
    requests_mock.get(
        f"{base_api}/courses/{course_id}/modules?page=2",
        json=[{"id": 2, "name": "Module 2", "position": 2}],
    )

    # Module 1 items (single page)
    requests_mock.get(
        f"{base_api}/courses/{course_id}/modules/1/items",
        json=[{"id": 11, "title": "Intro Page", "type": "Page", "position": 1, "page_url": "intro"}]
    )

    # Module 2 items (simulate pagination here too) — unquoted rel=next
    requests_mock.get(
        f"{base_api}/courses/{course_id}/modules/2/items",
        json=[{"id": 21, "title": "Assignment A", "type": "Assignment", "position": 1, "content_id": 201}],
        headers={"Link": f'<{base_api}/courses/{course_id}/modules/2/items?page=2>; rel=next'}
    )

    requests_mock.get(
        f"{base_api}/courses/{course_id}/modules/2/items?page=2",
        json=[{"id": 22, "title": "Discussion B", "type": "Discussion", "position": 2, "content_id": 301}]
    )

    # Use a fresh client so we don't depend on global source_api
    api_client = CanvasAPI(base_api, "tkn")

    export_root = tmp_path / "export" / "data"
    metadata = export_modules(course_id, export_root, api_client)

    assert len(metadata) == 2
    assert metadata[0]["name"] == "Module 1"
    assert len(metadata[0]["items"]) == 1
    assert metadata[1]["name"] == "Module 2"
    assert len(metadata[1]["items"]) == 2
    assert metadata[1]["items"][0]["title"] == "Assignment A"
    assert metadata[1]["items"][1]["title"] == "Discussion B"

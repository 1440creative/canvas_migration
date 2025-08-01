#tests/test_export_modules_pagination.py
from export.export_modules import export_modules

def test_export_modules_pagination(tmp_output, requests_mock):
    course_id = 303
    base_url = "https://canvas.test/api/v1"

    # Page 1 of modules (with Link header for next)
    requests_mock.get(
        f"{base_url}/courses/{course_id}/modules",
        json=[{"id": 1, "name": "Module 1", "position": 1}],
        headers={"Link": f'<{base_url}/courses/{course_id}/modules?page=2>; rel="next"'}
    )

    # Page 2 of modules
    requests_mock.get(
        f"{base_url}/courses/{course_id}/modules?page=2",
        json=[{"id": 2, "name": "Module 2", "position": 2}]
    )

    # Module 1 items (single page)
    requests_mock.get(
        f"{base_url}/courses/{course_id}/modules/1/items",
        json=[{"id": 11, "title": "Intro Page", "type": "Page", "position": 1, "page_url": "intro"}]
    )

    # Module 2 items (simulate pagination here too)
    requests_mock.get(
        f"{base_url}/courses/{course_id}/modules/2/items",
        json=[{"id": 21, "title": "Assignment A", "type": "Assignment", "position": 1, "content_id": 201}],
        headers={"Link": f'<{base_url}/courses/{course_id}/modules/2/items?page=2>; rel="next"'}
    )

    requests_mock.get(
        f"{base_url}/courses/{course_id}/modules/2/items?page=2",
        json=[{"id": 22, "title": "Discussion B", "type": "Discussion", "position": 2, "content_id": 301}]
    )

    # Patch base_url for API
    from utils import api
    api.source_api.base_url = f"{base_url}/"

    metadata = export_modules(course_id, output_dir=str(tmp_output))

    # Assertions
    assert len(metadata) == 2
    assert metadata[0]["name"] == "Module 1"
    assert len(metadata[0]["items"]) == 1
    assert metadata[1]["name"] == "Module 2"
    assert len(metadata[1]["items"]) == 2
    assert metadata[1]["items"][0]["title"] == "Assignment A"
    assert metadata[1]["items"][1]["title"] == "Discussion B"

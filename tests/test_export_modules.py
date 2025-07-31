# tests/test_export_modules.py
from export.export_modules import export_modules

def test_export_modules_with_items(tmp_output, requests_mock):
    course_id = 101

    # Mock modules list
    requests_mock.get(
        f"https://canvas.test/api/v1/courses/{course_id}/modules",
        json=[{"id": 1, "name": "Module 1", "position": 1}]
    )

    # Mock items for module 1
    requests_mock.get(
        f"https://canvas.test/api/v1/courses/{course_id}/modules/1/items",
        json=[{
            "id": 11,
            "title": "Intro Page",
            "type": "Page",
            "position": 1,
            "page_url": "intro"
        }]
    )

    from utils import api
    api.source_api.base_url = "https://canvas.test/api/v1/"

    metadata = export_modules(course_id, output_dir=str(tmp_output))

    assert len(metadata) == 1
    assert metadata[0]["name"] == "Module 1"
    assert len(metadata[0]["items"]) == 1
    assert metadata[0]["items"][0]["title"] == "Intro Page"

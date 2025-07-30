# tests/test_export_modules.py
from export.export_modules import export_modules

def test_export_modules_pagination(tmp_output, requests_mock):
    course_id = 101

    # First page of modules
    requests_mock.get(
        f"https://canvas.test/api/v1/courses/{course_id}/modules",
        json=[{"id": 1, "name": "Week 1", "position": 1}],
        headers={"Link": f'<https://canvas.test/api/v1/courses/{course_id}/modules?page=2>; rel="next"'}
    )

    # Second page of modules
    requests_mock.get(
        f"https://canvas.test/api/v1/courses/{course_id}/modules?page=2",
        json=[{"id": 2, "name": "Week 2", "position": 2}]
    )

    # Module items (no pagination for simplicity here)
    requests_mock.get(
        f"https://canvas.test/api/v1/courses/{course_id}/modules/1/items",
        json=[{"id": 11, "type": "Page", "title": "Intro", "position": 1, "page_url": "intro"}]
    )
    requests_mock.get(
        f"https://canvas.test/api/v1/courses/{course_id}/modules/2/items",
        json=[{"id": 21, "type": "Page", "title": "Next", "position": 1, "page_url": "next"}]
    )

    from utils import api
    api.source_api.base_url = "https://canvas.test/api/v1/"

    metadata = export_modules(course_id, output_dir=str(tmp_output))

    assert len(metadata) == 2
    assert metadata[0]["title"] == "Week 1"
    assert metadata[1]["title"] == "Week 2"

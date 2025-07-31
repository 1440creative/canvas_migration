import json
from export.export_assignments import export_assignments

def test_export_assignments(tmp_output, requests_mock):
    course_id = 101
    # Mock assignments list
    requests_mock.get(
        f"https://canvas.test/api/v1/courses/{course_id}/assignments",
        json=[{
            "id": 1,
            "name": "Essay 1",
            "description": "<p>Write an essay</p>",
            "points_possible": 10,
            "due_at": "2025-09-01T00:00:00Z",
            "published": True
        }]
    )

    from utils import api
    api.source_api.base_url = "https://canvas.test/api/v1/"

    metadata = export_assignments(course_id, output_dir=str(tmp_output))

    # Assertions
    assert len(metadata) == 1
    assert metadata[0]["name"] == "Essay 1"

    # Verify HTML file was written
    html_file = tmp_output / str(course_id) / "assignments" / "assignment_1.html"
    with open(html_file, "r", encoding="utf-8") as f:
        contents = f.read()
    assert "<p>Write an essay</p>" in contents

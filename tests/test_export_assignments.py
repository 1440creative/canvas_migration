# tests/test_export_assignments.py

import json
from pathlib import Path
from export.export_assignments import export_assignments

def test_export_assignments(tmp_output, requests_mock):
    course_id = 101

    # Mock the Canvas API assignments endpoint
    requests_mock.get(
        f"https://canvas.test/api/v1/courses/{course_id}/assignments",
        json=[
            {
                "id": 1,
                "name": "Essay 1",
                "description": "<p>Write an essay</p>",
                "points_possible": 10,
                "due_at": "2025-09-01T00:00:00Z",
                "published": True
            }
        ]
    )

    from utils import api
    api.source_api.base_url = "https://canvas.test/api/v1/"

    metadata = export_assignments(course_id, output_dir=tmp_output)

    # Check that one assignment was exported
    assert len(metadata) == 1
    assert metadata[0]["name"] == "Essay 1"

    # Check that the HTML description file was saved correctly
    html_file = tmp_output / str(course_id) / "assignments" / "assignment_1.html"
    assert html_file.exists()
    with html_file.open("r", encoding="utf-8") as f:
        content = f.read()
    assert "<p>Write an essay</p>" in content

    # Check that metadata json file exists
    meta_file = tmp_output / str(course_id) / "assignments_metadata.json"
    assert meta_file.exists()
    with meta_file.open("r", encoding="utf-8") as f:
        meta_json = json.load(f)
    assert any(a["id"] == 1 for a in meta_json)

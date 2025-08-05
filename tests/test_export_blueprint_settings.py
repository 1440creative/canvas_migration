# tests/test_export_blueprint_settings.py

from export.export_blueprint_settings import export_blueprint_settings
import json

def test_export_blueprint_settings(tmp_path, requests_mock):
    course_id = 606
    blueprint_url = f"https://canvas.sfu.ca/api/v1/courses/{course_id}/blueprint_templates/default"

    mock_data = {
        "id": 123,
        "course_id": course_id,
        "template_name": "Default Blueprint",
        "template_points": True,
        "locked": False
    }

    requests_mock.get(blueprint_url, json=mock_data)

    export_blueprint_settings(course_id, output_dir=tmp_path)

    saved_path = tmp_path / str(course_id) / "blueprint_settings.json"
    assert saved_path.exists()

    with saved_path.open() as f:
        data = json.load(f)
        assert data == mock_data
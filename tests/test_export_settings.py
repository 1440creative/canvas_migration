import json
from export.export_settings import export_settings

def test_export_settings(tmp_path, requests_mock):
    course_id = 606
    
    # Patch the API base URL to match the mocked URL
    from utils import api
    api.source_api.base_url = "https://canvas.test/api/v1/"

    fake_settings = {
        "allow_student_forum_attachments": True,
        "hide_final_grades": True,
        "default_view": "modules"
    }

    requests_mock.get(
        f"https://canvas.test/api/v1/courses/{course_id}/settings",
        json=fake_settings
    )

    export_settings(course_id, tmp_path)

    settings_file = tmp_path / str(course_id) / "course_settings.json"
    assert settings_file.exists()

    with settings_file.open("r", encoding="utf-8") as f:
        data = json.load(f)

    assert data == fake_settings
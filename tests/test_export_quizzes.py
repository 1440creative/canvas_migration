from export.export_quizzes import export_quizzes
import json

def test_export_quizzes(tmp_path, requests_mock):
    course_id = 606
    quizzes_url = f"https://canvas.sfu.ca/api/v1/courses/{course_id}/quizzes"

    mock_data = [
        {"id": 1, "title": "Quiz 1", "published": True},
        {"id": 2, "title": "Quiz 2", "published": False}
    ]

    requests_mock.get(quizzes_url, json=mock_data)

    # Make sure base_url is patched correctly
    from utils import api
    api.source_api.base_url = "https://canvas.sfu.ca/api/v1/"

    export_quizzes(course_id, output_dir=tmp_path)

    saved_path = tmp_path / str(course_id) / "quizzes.json"
    assert saved_path.exists()

    with saved_path.open() as f:
        data = json.load(f)
        assert data == mock_data
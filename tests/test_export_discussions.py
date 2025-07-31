import json
from export.export_discussions import export_discussions

def test_export_discussions(tmp_output, requests_mock):
    course_id = 101
    # Mock discussions list
    requests_mock.get(
        f"https://canvas.test/api/v1/courses/{course_id}/discussion_topics",
        json=[{
            "id": 5,
            "title": "Week 1 Discussion",
            "message": "<p>Discuss here</p>",
            "discussion_type": "threaded",
            "published": True
        }]
    )

    from utils import api
    api.source_api.base_url = "https://canvas.test/api/v1/"

    metadata = export_discussions(course_id, output_dir=str(tmp_output))

    # Assertions
    assert len(metadata) == 1
    assert metadata[0]["title"] == "Week 1 Discussion"

    # Verify HTML file
    html_file = tmp_output / str(course_id) / "discussions" / "discussion_5.html"
    with open(html_file, "r", encoding="utf-8") as f:
        contents = f.read()
    assert "<p>Discuss here</p>" in contents

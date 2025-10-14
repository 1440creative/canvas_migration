# tests/test_import_announcements.py

import json
from pathlib import Path
from tests.conftest import DummyCanvas, load_importer

def test_import_announcement_basic(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    a_dir = export_root / "announcements" / "welcome-week"
    a_dir.mkdir(parents=True)

    meta = {"id": 88, "title": "Welcome Week", "delayed_post_at": None}
    (a_dir / "announcement_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    (a_dir / "body.html").write_text("<p>Classes start Monday!</p>", encoding="utf-8")

    api_base = "https://api.example.edu"
    course_id = 777
    create_url = f"{api_base}/api/v1/courses/{course_id}/discussion_topics"

    # verify payload contains is_announcement=True and correct fields
    def _match(request):
        body = request.json()
        return (
            body.get("title") == "Welcome Week"
            and body.get("is_announcement") is True
            and "Classes start Monday!" in body.get("message", "")
        )

    post_m = requests_mock.post(create_url, additional_matcher=_match, json={"id": 999}, status_code=200)

    canvas = DummyCanvas(api_base)
    importer = load_importer(Path.cwd())  # gives us importer.import_announcements via dynamic import

    id_map = {}
    counters = importer.import_announcements(
        target_course_id=course_id,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
    )

    assert counters["imported"] == 1
    assert counters["failed"] == 0
    assert post_m.called
    assert id_map["announcements"][88] == 999


def test_import_announcement_alt_html_name(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    a_dir = export_root / "announcements" / "policy-update"
    a_dir.mkdir(parents=True)

    meta = {"id": 42, "title": "Policy Update", "html_path": "message.html", "pinned": True, "locked": True}
    (a_dir / "announcement_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    (a_dir / "message.html").write_text("<p>Please read.</p>", encoding="utf-8")

    api_base = "https://api.example.edu"
    course_id = 777
    create_url = f"{api_base}/api/v1/courses/{course_id}/discussion_topics"
    requests_mock.post(create_url, json={"id": 314}, status_code=200)

    canvas = DummyCanvas(api_base)
    importer = load_importer(Path.cwd())
    id_map = {}
    counters = importer.import_announcements(
        target_course_id=course_id,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
    )

    assert counters["imported"] == 1
    assert id_map["announcements"][42] == 314
    update_call = next(call for call in canvas.put_calls if "/courses/777/discussion_topics/314" in call["endpoint"])
    assert update_call["json"]["discussion_topic"] == {"pinned": True, "locked": True}

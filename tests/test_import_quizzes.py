# tests/test_import_quizzes.py
import json
from pathlib import Path

from tests.conftest import DummyCanvas
from importers import import_quizzes as importer


def test_import_quizzes_basic(tmp_path, requests_mock):
    # --- Arrange export tree
    export_root = tmp_path / "export" / "data" / "101"
    q_dir = export_root / "quizzes" / "quiz-1"
    q_dir.mkdir(parents=True)

    meta = {
        "id": 77,
        "title": "Quiz 1",
        "published": True,
        # optional fields your importer might pass through:
        "shuffle_answers": True,
        "time_limit": 10,
    }
    (q_dir / "quiz_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    (q_dir / "description.html").write_text("<p>Good luck!</p>", encoding="utf-8")

    # --- Arrange API mocks
    api_base = "https://api.example.edu"
    create_url = f"{api_base}/api/v1/courses/222/quizzes"
    requests_mock.post(create_url, json={"id": 9001}, status_code=200)

    canvas = DummyCanvas(api_base)
    id_map = {}

    # --- Act
    counters = importer.import_quizzes(
        target_course_id=222,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
        include_questions=False,  # keep it simple for this test
    )

    # --- Assert
    assert counters["imported"] == 1
    assert counters["failed"] == 0
    assert id_map["quizzes"][77] == 9001


def test_import_quizzes_location_follow(tmp_path, requests_mock):
    # --- Arrange export tree
    export_root = tmp_path / "export" / "data" / "101"
    q_dir = export_root / "quizzes" / "quiz-2"
    q_dir.mkdir(parents=True)

    meta = {"id": 88, "title": "Quiz 2", "published": False}
    (q_dir / "quiz_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    (q_dir / "index.html").write_text("<p>Another quiz</p>", encoding="utf-8")

    # --- Arrange API mocks
    api_base = "https://api.example.edu"
    create_url = f"{api_base}/api/v1/courses/333/quizzes"
    follow_url = f"{api_base}/api/v1/courses/333/quizzes/1234"

    # POST returns 201 + Location header, body missing id -> importer should follow
    requests_mock.post(create_url, json={}, status_code=201, headers={"Location": follow_url})
    requests_mock.get(follow_url, json={"id": 1234}, status_code=200)

    canvas = DummyCanvas(api_base)
    id_map = {}

    # --- Act
    counters = importer.import_quizzes(
        target_course_id=333,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
        include_questions=False,
    )

    # --- Assert
    assert counters["imported"] == 1
    assert counters["failed"] == 0
    assert id_map["quizzes"][88] == 1234

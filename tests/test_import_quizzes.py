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
        "assignment_id": 5001,
        "assignment_group_id": 2001,
    }
    (q_dir / "quiz_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    (q_dir / "description.html").write_text("<p>Good luck!</p>", encoding="utf-8")

    # --- Arrange API mocks
    api_base = "https://api.example.edu"
    create_url = f"{api_base}/api/v1/courses/222/quizzes"
    requests_mock.post(create_url, json={"id": 9001, "assignment_id": 6001}, status_code=200)
    update_url = f"{api_base}/api/v1/courses/222/assignments/6001"
    update_matcher = requests_mock.put(update_url, json={"id": 6001}, status_code=200)

    canvas = DummyCanvas(api_base)
    id_map = {"assignment_groups": {2001: 3001}}

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
    assert id_map["assignments"][5001] == 6001
    assert update_matcher.called
    create_payload = requests_mock.request_history[0].json()
    assert create_payload["quiz"]["assignment_group_id"] == 3001


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

def test_import_quizzes_with_questions(tmp_path, requests_mock):
    # --- Arrange export tree
    export_root = tmp_path / "export" / "data" / "101"
    q_dir = export_root / "quizzes" / "quiz-3"
    q_dir.mkdir(parents=True)

    meta = {"id": 99, "title": "Quiz 3", "published": True}
    (q_dir / "quiz_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    (q_dir / "description.html").write_text("<p>Third quiz</p>", encoding="utf-8")

    # Two simple questions in Canvas-style structure
    questions = [
        {
            "question_name": "True/False",
            "question_text": "Snow is white.",
            "question_type": "true_false_question",
            "answers": [{"answer_text": "True", "answer_weight": 100}, {"answer_text": "False", "answer_weight": 0}],
            "points_possible": 1
        },
        {
            "question_name": "Multiple Choice",
            "question_text": "Pick one",
            "question_type": "multiple_choice_question",
            "answers": [
                {"answer_text": "A", "answer_weight": 0},
                {"answer_text": "B", "answer_weight": 100},
                {"answer_text": "C", "answer_weight": 0},
            ],
            "points_possible": 2
        },
    ]
    (q_dir / "questions.json").write_text(json.dumps(questions), encoding="utf-8")

    # --- Arrange API mocks
    api_base = "https://api.example.edu"
    course_id = 444
    create_url = f"{api_base}/api/v1/courses/{course_id}/quizzes"
    questions_url = f"{api_base}/api/v1/courses/{course_id}/quizzes/555/questions"

    # Create quiz returns id
    create_matcher = requests_mock.post(create_url, json={"id": 555, "assignment_id": 7555}, status_code=200)
    update_url = f"{api_base}/api/v1/courses/{course_id}/assignments/7555"
    update_matcher = requests_mock.put(update_url, json={"id": 7555}, status_code=200)
    # Question posts (same URL hit twice)
    questions_matcher = requests_mock.post(questions_url, json={"id": 9000}, status_code=200)

    canvas = DummyCanvas(api_base)
    id_map = {}

    # --- Act
    counters = importer.import_quizzes(
        target_course_id=course_id,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
        include_questions=True,
    )

    # --- Assert
    assert counters["imported"] == 1
    assert counters["failed"] == 0
    assert id_map["quizzes"][99] == 555

    # Ensure we created the quiz and posted both questions
    assert create_matcher.called
    assert questions_matcher.call_count == len(questions)
    assert not update_matcher.called  # no assignment_group_id provided so no update

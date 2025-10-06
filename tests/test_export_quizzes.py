# tests/test_export_quizzes.py
from pathlib import Path
import json

from export.export_quizzes import export_quizzes


class DummyAPI:
    """
    Minimal stand-in for utils.api.CanvasAPI:
      - has .api_root
      - implements .get(endpoint, params=None) returning pre-baked data
    No real HTTP calls are made; this keeps the test stable and fast.
    """
    def __init__(self, api_root: str, course_id: int, detail_by_id: dict, questions_by_id: dict | None = None, assignments_by_id: dict | None = None):
        # api_root must look like ".../api/v1/"
        self.api_root = api_root if api_root.endswith("/") else api_root + "/"
        self._course_id = course_id
        self._detail_by_id = detail_by_id
        self._questions_by_id = questions_by_id or {}
        self._assignments_by_id = assignments_by_id or {}

    def get(self, endpoint: str, params=None):
        # Normalize endpoints that the exporter calls:
        #   courses/{cid}/quizzes
        #   courses/{cid}/quizzes/{id}
        #   courses/{cid}/quizzes/{id}/questions
        ep = endpoint.strip().lstrip("/")
        if ep.startswith("api/v1/"):
            ep = ep[len("api/v1/"):]
        parts = ep.split("/")

        # quizzes list
        if parts == ["courses", str(self._course_id), "quizzes"]:
            # Return a simple list with minimal fields; exporter fetches detail next
            return [{"id": i, "title": d.get("title", f"quiz-{i}"), "published": d.get("published", True)}
                    for i, d in sorted(self._detail_by_id.items())]

        # quiz detail or questions
        if len(parts) >= 4 and parts[0] == "courses" and parts[2] == "quizzes":
            qid = int(parts[3])
            if len(parts) == 4:
                # detail
                return self._detail_by_id[qid]
            if len(parts) == 5 and parts[4] == "questions":
                return self._questions_by_id.get(qid, [])

        if len(parts) == 4 and parts[0] == "courses" and parts[2] == "assignments":
            aid = int(parts[3])
            return self._assignments_by_id.get(aid, {})
        raise AssertionError(f"Unexpected endpoint in DummyAPI.get(): {endpoint!r}")


def _read_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def test_export_quizzes_minimal(tmp_path: Path):
    course_id = 606
    export_root = tmp_path  # exporter will write to export_root/{course_id}/quizzes/...

    # Two quizzes with different titles. One uses Canvas 'graded_quiz' (normalize -> 'assignment').
    quiz_details = {
        1: {
            "id": 1,
            "title": "Quiz 1",
            "published": True,
            "description": "<p>Q1</p>",
            "quiz_type": "graded_quiz",      # should normalize to "assignment" in metadata
            "points_possible": 5,
            "time_limit": 10,
            "allowed_attempts": 1,
            "shuffle_answers": True,
            "scoring_policy": "keep_highest",
            "one_question_at_a_time": True,
            "due_at": None,
            "unlock_at": None,
            "lock_at": None,
            "updated_at": "2025-01-01T00:00:00Z",
        },
        2: {
            "id": 2,
            "title": "Quiz 2",
            "published": False,
            "description": "<p>Q2</p>",
            "quiz_type": "practice_quiz",
            "points_possible": None,
            "time_limit": None,
            "allowed_attempts": -1,
            "shuffle_answers": False,
            "scoring_policy": "keep_latest",
            "one_question_at_a_time": False,
            "due_at": "2025-02-01T12:00:00Z",
            "unlock_at": None,
            "lock_at": None,
            "updated_at": "2025-02-01T00:00:00Z",
        },
    }

    api = DummyAPI(
        api_root="https://canvas.sfu.ca/api/v1/",
        course_id=course_id,
        detail_by_id=quiz_details,
    )

    exported = export_quizzes(course_id=course_id, export_root=export_root, api=api, include_questions=False)
    assert isinstance(exported, list) and len(exported) == 2

    course_root = export_root / str(course_id)
    quizzes_root = course_root / "quizzes"
    assert quizzes_root.exists()

    # There should be exactly two quiz directories (001_*, 002_*), each with index.html + quiz_metadata.json
    quiz_dirs = sorted([p for p in quizzes_root.iterdir() if p.is_dir()])
    assert len(quiz_dirs) == 2

    for q_dir in quiz_dirs:
        html = q_dir / "index.html"
        meta_path = q_dir / "quiz_metadata.json"
        assert html.exists()
        assert meta_path.exists()

        meta = _read_json(meta_path)

        # Basic fields exist and are correctly typed
        assert "id" in meta and "title" in meta and "published" in meta
        assert "quiz_type" in meta and "html_path" in meta and "updated_at" in meta
        assert "module_item_ids" in meta and isinstance(meta["module_item_ids"], list)

        # html_path should be POSIX relative to course_root and point to index.html
        expected_rel = (q_dir / "index.html").relative_to(course_root).as_posix()
        assert meta["html_path"] == expected_rel

        # source_api_url should be built from api_root + course/quiz path
        assert meta["source_api_url"].startswith("https://canvas.sfu.ca/api/v1/courses/")
        assert str(course_id) in meta["source_api_url"]
        assert f"/quizzes/{meta['id']}" in meta["source_api_url"]

    # Verify normalization of quiz_type for quiz 1 (graded_quiz -> assignment)
    metas_by_id = {m["id"]: m for m in exported}
    assert metas_by_id[1]["quiz_type"] == "assignment"
    assert metas_by_id[2]["quiz_type"] == "practice_quiz"


def test_export_quizzes_with_questions(tmp_path: Path):
    course_id = 777
    export_root = tmp_path

    # Provide positions so we can assert deterministic ordering in questions.json
    quiz_details = {
        10: {
            "id": 10,
            "title": "With Questions",
            "published": True,
            "description": "<p>Body</p>",
            "quiz_type": "graded_quiz",
            "updated_at": "2025-03-01T00:00:00Z",
        },
    }
    questions_for_10 = [
        {"id": 3, "position": 2, "question_name": "Q2"},
        {"id": 1, "position": 1, "question_name": "Q1"},
        {"id": 2, "position": 2, "question_name": "Q2b"},
    ]
    api = DummyAPI(
        api_root="https://canvas.sfu.ca/api/v1/",
        course_id=course_id,
        detail_by_id=quiz_details,
        questions_by_id={10: questions_for_10},
    )

    exported = export_quizzes(course_id=course_id, export_root=export_root, api=api, include_questions=True)
    assert len(exported) == 1

    course_root = export_root / str(course_id)
    quizzes_root = course_root / "quizzes"
    quiz_dirs = [p for p in quizzes_root.iterdir() if p.is_dir()]
    assert len(quiz_dirs) == 1

    q_dir = quiz_dirs[0]
    q_json = _read_json(q_dir / "questions.json")

    # The exporter sorts questions by (position, id). Expected order ids: 1, 2, 3? Wait:
    # positions: [2,1,2] with ids [3,1,2] -> sort by position asc, then id asc => (1,1), (2,2), (2,3) -> ids [1,2,3]
    assert [q["id"] for q in q_json] == [1, 2, 3]

    # Metadata also present and html_path correct
    meta = _read_json(q_dir / "quiz_metadata.json")
    assert meta["id"] == 10
    expected_rel = (q_dir / "index.html").relative_to(course_root).as_posix()
    assert meta["html_path"] == expected_rel


def test_export_quizzes_includes_assignment_group(tmp_path: Path):
    course_id = 888
    export_root = tmp_path

    quiz_details = {
        5: {
            "id": 5,
            "title": "Weighted Quiz",
            "description": "<p>Body</p>",
            "quiz_type": "graded_quiz",
            "assignment_id": 5005,
        }
    }
    assignments = {
        5005: {
            "id": 5005,
            "assignment_group_id": 321,
        }
    }

    api = DummyAPI(
        api_root="https://canvas.sfu.ca/api/v1/",
        course_id=course_id,
        detail_by_id=quiz_details,
        assignments_by_id=assignments,
    )

    exported = export_quizzes(course_id=course_id, export_root=export_root, api=api, include_questions=False)
    assert exported[0]["assignment_id"] == 5005
    assert exported[0]["assignment_group_id"] == 321

    meta = _read_json((export_root / str(course_id) / "quizzes" / "001_weighted-quiz" / "quiz_metadata.json"))
    assert meta["assignment_id"] == 5005
    assert meta["assignment_group_id"] == 321

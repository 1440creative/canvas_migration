# tests/test_export_quizzes_refactor.py
from __future__ import annotations

import json
from pathlib import Path
import requests_mock

from utils.api import CanvasAPI
from export.export_quizzes import export_quizzes


def test_export_quizzes_basic(tmp_path: Path):
    course_id = 303
    root = tmp_path / "export" / "data"
    api = CanvasAPI("https://canvas.test", "tkn")

    with requests_mock.Mocker() as m:
        # list
        m.get(f"https://canvas.test/api/v1/courses/{course_id}/quizzes",
              json=[{"id": 77, "title": "Midterm Quiz", "position": 1, "published": True}])

        # detail
        m.get(f"https://canvas.test/api/v1/courses/{course_id}/quizzes/77",
              json={
                  "id": 77,
                  "title": "Midterm Quiz",
                  "description": "<p>Read chapters 1-3</p>",
                  "published": True,
                  "quiz_type": "graded_quiz",
                  "time_limit": 60,
                  "shuffle_answers": True,
                  "allowed_attempts": 1,
                  "hide_results": None,
                  "due_at": None,
              })

        metas = export_quizzes(course_id, root, api, include_questions=False)

    q_dir = root / str(course_id) / "quizzes" / "001_midterm-quiz"
    assert (q_dir / "index.html").exists()
    meta = json.loads((q_dir / "quiz_metadata.json").read_text(encoding="utf-8"))

    assert metas[0]["id"] == 77
    assert meta["title"] == "Midterm Quiz"
    assert meta["module_item_ids"] == []
    assert meta["html_path"].endswith("quizzes/001_midterm-quiz/index.html")


def test_export_quizzes_with_questions(tmp_path: Path):
    course_id = 304
    root = tmp_path / "export" / "data"
    api = CanvasAPI("https://canvas.test", "tkn")

    with requests_mock.Mocker() as m:
        # list + detail
        m.get(f"https://canvas.test/api/v1/courses/{course_id}/quizzes",
              json=[{"id": 88, "title": "Final Quiz", "position": 1, "published": True}])
        m.get(f"https://canvas.test/api/v1/courses/{course_id}/quizzes/88",
              json={"id": 88, "title": "Final Quiz", "description": "<p>All units</p>", "published": True})

        # questions
        m.get(f"https://canvas.test/api/v1/courses/{course_id}/quizzes/88/questions",
              json=[
                  {"id": 2, "position": 2, "question_name": "Q2"},
                  {"id": 1, "position": 1, "question_name": "Q1"},
              ])

        metas = export_quizzes(course_id, root, api, include_questions=True)

    q_dir = root / str(course_id) / "quizzes" / "001_final-quiz"
    questions = json.loads((q_dir / "questions.json").read_text(encoding="utf-8"))
    # Sorted by position, then id:
    assert [q["id"] for q in questions] == [1, 2]
    assert metas[0]["question_count"] == 2

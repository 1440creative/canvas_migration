# tests/test_import_quizzes.py
import json
import importlib.util
from pathlib import Path
import requests

from tests.conftest import DummyCanvas


def _load_quizzes_module(project_root: Path):
    mod_path = (project_root /"importers"/ "import_quizzes.py").resolve()
    assert mod_path.exists(), f"Expected module at {mod_path}"
    spec = importlib.util.spec_from_file_location("import_quizzes_mod", str(mod_path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader, f"Could not build spec for {mod_path}"
    spec.loader.exec_module(mod)
    assert hasattr(mod, "import_quizzes") and callable(mod.import_quizzes), \
        "import_quizzes not found or not callable"
    return mod


def test_import_quizzes_basic(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    qdir = export_root / "quizzes" / "intro"
    qdir.mkdir(parents=True)
    (qdir / "quiz_metadata.json").write_text(json.dumps({
        "id": 77,
        "title": "Intro Quiz",
        "quiz_type": "assignment",
        "published": True,
        "points_possible": 5
    }), encoding="utf-8")
    (qdir / "description.html").write_text("<p>Welcome</p>", encoding="utf-8")

    api_base = "https://api.example.edu"
    requests_mock.post(f"{api_base}/api/v1/courses/222/quizzes",
                       json={"id": 9001, "title": "Intro Quiz"}, status_code=200)

    canvas = DummyCanvas(api_base)
    mod = _load_quizzes_module(Path.cwd())
    id_map = {}

    mod.import_quizzes(
        target_course_id=222,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
        include_questions=False,
    )

    assert id_map["quizzes"] == {77: 9001}


def test_import_quizzes_with_questions(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    qdir = export_root / "quizzes" / "with-qs"
    qdir.mkdir(parents=True)
    (qdir / "quiz_metadata.json").write_text(json.dumps({
        "id": 88,
        "title": "With Questions",
        "quiz_type": "assignment",
        "published": True,
    }), encoding="utf-8")
    (qdir / "questions.json").write_text(json.dumps({
        "questions": [
            {"question_name": "Q1", "question_text": "1+1=?", "question_type": "multiple_choice_question",
             "answers": [{"answer_text": "2", "weight": 100}, {"answer_text": "3", "weight": 0}]},
            {"question_name": "Q2", "question_text": "True?", "question_type": "true_false_question",
             "answers": [{"answer_text": "True", "weight": 100}, {"answer_text": "False", "weight": 0}]}
        ]
    }), encoding="utf-8")

    api_base = "https://api.example.edu"
    # Create quiz
    requests_mock.post(f"{api_base}/api/v1/courses/333/quizzes",
                       json={"id": 9002, "title": "With Questions"}, status_code=200)
    # Create questions (two posts)
    requests_mock.post(f"{api_base}/api/v1/courses/333/quizzes/9002/questions",
                       json={"id": 1}, status_code=200)
    requests_mock.post(f"{api_base}/api/v1/courses/333/quizzes/9002/questions",
                       json={"id": 2}, status_code=200)

    canvas = DummyCanvas(api_base)
    mod = _load_quizzes_module(Path.cwd())
    id_map = {}

    mod.import_quizzes(
        target_course_id=333,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
        include_questions=True,
    )

    assert id_map["quizzes"] == {88: 9002}

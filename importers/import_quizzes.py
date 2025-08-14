# import/import_quizzes.py
"""
Import Quizzes into a Canvas course using your CanvasAPI-style wrapper.

Expected export layout (per quiz directory):
    quizzes/<something>/
      ├─ quiz_metadata.json         # fields align with QuizMeta (see models.py)
      ├─ (optional) description.html  or metadata["html_path"]
      └─ (optional) questions.json    or questions/*.json  (if you exported questions)

This importer:
  1) Loads quiz_metadata.json (+ description HTML if present).
  2) Creates the quiz via POST /api/v1/courses/{course_id}/quizzes.
  3) Optionally creates questions if include_questions=True and data present.
  4) Records id_map["quizzes"][old_id] = new_id.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, Optional, Protocol, List

import requests
from logging_setup import get_logger

__all__ = ["import_quizzes"]


class CanvasLike(Protocol):
    session: requests.Session
    api_root: str
    def post(self, endpoint: str, **kwargs) -> requests.Response: ...
    def put(self, endpoint: str, **kwargs) -> requests.Response: ...
    def post_json(self, endpoint: str, *, payload: Dict[str, Any]) -> Dict[str, Any]: ...


# ---------- helpers ----------
def _read_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _read_text_if_exists(path: Path) -> Optional[str]:
    return path.read_text(encoding="utf-8") if path.exists() else None

def _coerce_int(val: Any) -> Optional[int]:
    try:
        return int(val) if val is not None else None
    except (TypeError, ValueError):
        return None

# Allowed quiz fields Canvas accepts in "quiz" envelope.
_ALLOWED_FIELDS = {
    "title", "quiz_type", "description", "published",
    "shuffle_answers", "time_limit", "allowed_attempts",
    "scoring_policy", "one_question_at_a_time",
    "due_at", "lock_at", "unlock_at",
    "points_possible",
}

def _build_quiz_payload(meta: Dict[str, Any], description_html: Optional[str]) -> Dict[str, Any]:
    quiz: Dict[str, Any] = {}
    for k in _ALLOWED_FIELDS:
        if k in meta and meta[k] is not None:
            quiz[k] = meta[k]
    # prefer file HTML for description
    if description_html is not None:
        quiz["description"] = description_html
    # normalize: Canvas expects "title"
    if "name" in meta and not quiz.get("title"):
        quiz["title"] = meta["name"]
    return {"quiz": quiz}

def _load_questions(quiz_dir: Path) -> Optional[List[Dict[str, Any]]]:
    # Prefer a single questions.json; otherwise gather questions/*.json
    qfile = quiz_dir / "questions.json"
    if qfile.exists():
        data = _read_json(qfile)
        # allow either {"questions":[...]} or a raw list
        if isinstance(data, dict) and "questions" in data:
            return list(data["questions"])
        if isinstance(data, list):
            return list(data)
        return None

    questions_dir = quiz_dir / "questions"
    if questions_dir.exists():
        qs: List[Dict[str, Any]] = []
        for f in sorted(questions_dir.glob("*.json")):
            obj = _read_json(f)
            if isinstance(obj, dict):
                qs.append(obj)
        return qs if qs else None
    return None


# ---------- public entrypoint ----------
def import_quizzes(
    *,
    target_course_id: int,
    export_root: Path,
    canvas: CanvasLike,
    id_map: Dict[str, Dict[int, int]],
    include_questions: bool = False,
) -> None:
    """
    Create quizzes (and optionally their questions) and update id_map["quizzes"].
    """
    logger = get_logger(course_id=target_course_id, artifact="quizzes")

    q_dir = export_root / "quizzes"
    if not q_dir.exists():
        logger.warning("No quizzes directory found at %s", q_dir)
        return

    logger.info("Starting quizzes import from %s", q_dir)

    quiz_id_map = id_map.setdefault("quizzes", {})
    imported = 0
    skipped = 0
    failed = 0

    for meta_file in q_dir.rglob("quiz_metadata.json"):
        meta: Dict[str, Any]
        try:
            meta = _read_json(meta_file)
        except Exception as e:
            failed += 1
            logger.exception("Failed to read %s: %s", meta_file, e)
            continue

        old_id = _coerce_int(meta.get("id"))
        title = meta.get("title") or meta.get("name")
        if not title:
            skipped += 1
            logger.warning("Skipping %s (missing quiz title)", meta_file)
            continue

        # Resolve description HTML path
        html_rel = meta.get("html_path") or "description.html"
        html_path = meta_file.parent / html_rel
        description_html = _read_text_if_exists(html_path)

        try:
            payload = _build_quiz_payload(meta, description_html)
            create_resp = canvas.post(f"/api/v1/courses/{target_course_id}/quizzes", json=payload)
            create_resp.raise_for_status()
            created = create_resp.json()
            new_quiz_id = _coerce_int(created.get("id"))

            if include_questions:
                qs = _load_questions(meta_file.parent)
                if qs:
                    _create_questions_bulk(canvas, target_course_id, new_quiz_id, qs, logger)

            if old_id is not None and new_quiz_id is not None:
                quiz_id_map[old_id] = new_quiz_id

            imported += 1
            logger.info("Created quiz '%s' old_id=%s new_id=%s", title, old_id, new_quiz_id)

        except Exception as e:
            failed += 1
            logger.exception("Failed to create quiz from %s: %s", meta_file.parent, e)

    logger.info(
        "Quizzes import complete. imported=%d skipped=%d failed=%d total=%d",
        imported, skipped, failed, imported + skipped + failed
    )


# ---------- questions creation ----------
def _create_questions_bulk(
    canvas: CanvasLike,
    course_id: int,
    quiz_id: Optional[int],
    questions: List[Dict[str, Any]],
    logger,
) -> None:
    """
    Create questions one by one via POST /courses/{course_id}/quizzes/{quiz_id}/questions.
    The payload is {"question": {...}} per Canvas API.
    """
    if not quiz_id:
        logger.warning("No quiz_id returned; skipping questions")
        return

    for q in questions:
        payload = {"question": q}
        resp = canvas.post(f"/api/v1/courses/{course_id}/quizzes/{quiz_id}/questions", json=payload)
        resp.raise_for_status()

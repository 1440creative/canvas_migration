# export/export_quizzes.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from logging_setup import get_logger
from utils.api import CanvasAPI, source_api
from utils.fs import ensure_dir, atomic_write, json_dumps_stable, safe_relpath
from utils.strings import sanitize_slug


def export_quizzes(
    course_id: int,
    export_root: Optional[Path] = None,
    api: Optional[CanvasAPI] = None,
    include_questions: bool = False,
    output_dir: Optional[Path] = None,  # legacy alias
) -> List[Dict[str, Any]]:
    # Back-compat: allow output_dir alias and default API
    if export_root is None and output_dir is not None:
        export_root = output_dir
    if export_root is None:
        raise ValueError("export_root (or legacy output_dir) is required")

    if api is None:
        api = source_api
    """
    Export Canvas quizzes with deterministic structure.

    Layout:
      export/data/{course_id}/quizzes/{position:03d}_{slug}/index.html
                                                      └─ quiz_metadata.json
                                                      └─ questions.json   (optional)

    Notes:
      - Returns list of metadata dicts (compatible with a QuizMeta structure)
      - `module_item_ids` stays empty here; modules pass backfills it
    """
    
    log = get_logger(artifact="quizzes", course_id=course_id)

    course_root = export_root / str(course_id)
    quizzes_root = course_root / "quizzes"
    ensure_dir(quizzes_root)

    # 1) Fetch list
    log.info("fetching quizzes list", extra={"endpoint": f"courses/{course_id}/quizzes"})
    items = api.get(f"courses/{course_id}/quizzes", params={"per_page": 100})
    if not isinstance(items, list):
        raise TypeError("Expected list of quizzes from Canvas API")

    # 2) Deterministic sort: position (fallback big), then title/name, then id
    def sort_key(q: Dict[str, Any]):
        pos = q.get("position") if q.get("position") is not None else 999_999
        title = (q.get("title") or q.get("quiz_title") or q.get("name") or "").strip()
        qid = q.get("id") or 0
        return (pos, title, qid)

    items_sorted = sorted(items, key=sort_key)

    exported: List[Dict[str, Any]] = []

    # 3) Export each quiz
    for i, q in enumerate(items_sorted, start=1):
        qid = int(q["id"])
        # Detail
        detail = api.get(f"courses/{course_id}/quizzes/{qid}")
        if not isinstance(detail, dict):
            raise TypeError("Expected quiz detail dict from Canvas API")

        assignment_id = detail.get("assignment_id")
        assignment_group_id = detail.get("assignment_group_id")
        if assignment_group_id is None and assignment_id is not None:
            try:
                assignment_detail = api.get(f"courses/{course_id}/assignments/{assignment_id}")
                if isinstance(assignment_detail, dict):
                    assignment_group_id = assignment_detail.get("assignment_group_id")
            except Exception:
                assignment_group_id = assignment_group_id  # keep existing (likely None)

        title = (detail.get("title") or detail.get("quiz_title") or f"quiz-{qid}").strip()
        slug = sanitize_slug(title) or f"quiz-{qid}"

        q_dir = quizzes_root / f"{i:03d}_{slug}"
        ensure_dir(q_dir)

        # HTML from description
        html = detail.get("description") or ""
        html_path = q_dir / "index.html"
        atomic_write(html_path, html)

        # Optionally include questions
        question_count: Optional[int] = None
        if include_questions:
            questions = api.get(f"courses/{course_id}/quizzes/{qid}/questions", params={"per_page": 100})
            if isinstance(questions, list):
                # Deterministic order by position, id
                def qk(x: Dict[str, Any]):
                    pos = x.get("position") if x.get("position") is not None else 999_999
                    xid = x.get("id") or 0
                    return (pos, xid)
                questions_sorted = sorted(questions, key=qk)
                atomic_write(q_dir / "questions.json", json_dumps_stable(questions_sorted))
                question_count = len(questions_sorted)

        quiz_type_raw = detail.get("quiz_type")
        quiz_type = "assignment" if quiz_type_raw == "graded_quiz" else quiz_type_raw
        
        # Metadata (aligned with QuizMeta)
        meta: Dict[str, Any] = {
            "id": qid,
            "title": title,
            "position": i,
            "published": bool(detail.get("published", True)),
            "quiz_type": quiz_type,                            # practice_quiz | assignment | graded_survey | survey
            "points_possible": detail.get("points_possible"),
            "time_limit": detail.get("time_limit"),            # minutes or None
            "allowed_attempts": detail.get("allowed_attempts"),
            "shuffle_answers": detail.get("shuffle_answers"),
            "scoring_policy": detail.get("scoring_policy"),
            "one_question_at_a_time": detail.get("one_question_at_a_time"),
            "due_at": detail.get("due_at"),
            "unlock_at": detail.get("unlock_at"),
            "lock_at": detail.get("lock_at"),
            "html_path": safe_relpath(html_path, course_root), # importer prefers meta['html_path']
            "updated_at": detail.get("updated_at") or "",
            "question_count": question_count,
            "module_item_ids": [],  # backfilled by modules exporter
            "source_api_url": api.api_root.rstrip("/") + f"/courses/{course_id}/quizzes/{qid}",
        }
        #keep extra Canvas fields
        if "hide_results" in detail:
            meta["hide_results"] = detail["hide_results"]

        if assignment_id is not None:
            meta["assignment_id"] = assignment_id
        if assignment_group_id is not None:
            meta["assignment_group_id"] = assignment_group_id


        atomic_write(q_dir / "quiz_metadata.json", json_dumps_stable(meta))
        exported.append(meta)

        log.info(
            "exported quiz",
            extra={"quiz_id": qid, "slug": slug, "position": i, "html": meta["html_path"], "questions": question_count},
        )

    log.info("exported quizzes complete", extra={"count": len(exported)})
    return exported

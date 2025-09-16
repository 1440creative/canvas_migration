# importers/import_quizzes.py
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Protocol

import requests
from logging_setup import get_logger

__all__ = ["import_quizzes"]


class CanvasLike(Protocol):
    session: requests.Session
    api_root: str
    def post(self, endpoint: str, **kwargs) -> requests.Response: ...
    def get(self, endpoint: str, **kwargs) -> Any: ...


def _read_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _read_text_if_exists(p: Path) -> Optional[str]:
    return p.read_text(encoding="utf-8") if p.exists() else None

def _coerce_int(val: Any) -> Optional[int]:
    try:
        return int(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _pick_desc_html(dir_: Path, meta: Dict[str, Any]) -> str:
    rel = meta.get("html_path")
    candidates = [rel] if rel else []
    candidates += ["description.html", "index.html", "body.html", "overview.html"]
    for name in candidates:
        if not name:
            continue
        p = dir_ / name
        if p.exists():
            return _read_text_if_exists(p) or ""
    return ""


def import_quizzes(
    *,
    target_course_id: int,
    export_root: Path,
    canvas: CanvasLike,
    id_map: dict[str, dict],
    include_questions: bool = False,
) -> dict[str, int]:
    """
    Import classic quizzes:

      • POST /courses/:id/quizzes with {"quiz": {...}}
      • Optionally POST questions from questions.json:
          POST /courses/:id/quizzes/:quiz_id/questions with {"question": {...}}
      • Record id_map['quizzes'][old_id] = new_id
    """
    log = get_logger(course_id=target_course_id, artifact="quizzes")
    counters = {"imported": 0, "skipped": 0, "failed": 0, "total": 0, "questions": 0}

    q_dir = export_root / "quizzes"
    if not q_dir.exists():
        log.info("nothing-to-import at %s", q_dir)
        return counters

    id_map.setdefault("quizzes", {})

    limit_env = os.getenv("IMPORT_QUIZZES_LIMIT")
    limit: Optional[int] = int(limit_env) if (limit_env and limit_env.isdigit()) else None

    for item in sorted(q_dir.iterdir()):
        if not item.is_dir():
            continue

        meta_path = item / "quiz_metadata.json"
        if not meta_path.exists():
            counters["skipped"] += 1
            log.warning("missing_metadata dir=%s", item)
            continue

        try:
            meta = _read_json(meta_path)
        except Exception as e:
            counters["failed"] += 1
            log.exception("failed to read metadata %s: %s", meta_path, e)
            continue

        counters["total"] += 1

        title = meta.get("title") or meta.get("name")
        if not title:
            counters["skipped"] += 1
            log.warning("skipping (missing title) %s", meta_path)
            continue

        description_html = _pick_desc_html(item, meta)

        quiz: Dict[str, Any] = {
            "title": title,
            "description": description_html,
            "published": bool(meta.get("published", False)),
        }
        # Common optional fields
        for k in [
            "quiz_type", "time_limit", "shuffle_answers", "hide_results",
            "one_question_at_a_time", "cant_go_back", "allowed_attempts",
            "scoring_policy", "show_correct_answers", "due_at", "lock_at", "unlock_at",
            "points_possible"
        ]:
            if meta.get(k) is not None:
                quiz[k] = meta[k]

        old_id = _coerce_int(meta.get("id"))

        endpoint = f"/api/v1/courses/{target_course_id}/quizzes"
        log.debug("create quiz title=%r dir=%s", title, item)
        try:
            resp = canvas.post(endpoint, json={"quiz": quiz})
            try:
                data = resp.json()
            except ValueError:
                data = {}
        except Exception as e:
            counters["failed"] += 1
            log.exception("failed-create title=%s: %s", title, e)
            continue

        new_id = _coerce_int(data.get("id"))

        if new_id is None and "Location" in resp.headers:
            try:
                follow = canvas.session.get(resp.headers["Location"])
                follow.raise_for_status()
                try:
                    j2 = follow.json()
                except ValueError:
                    j2 = {}
                new_id = _coerce_int(j2.get("id"))
                data = j2 or data
            except Exception as e:
                log.debug("follow-location failed for quiz=%s: %s", title, e)

        if new_id is None:
            counters["failed"] += 1
            log.error("failed-create (no id) title=%s", title)
            continue

        if old_id is not None:
            id_map["quizzes"][old_id] = new_id

        # Questions (optional)
        if include_questions:
            q_json = item / "questions.json"
            if q_json.exists():
                try:
                    payload = _read_json(q_json)
                    questions = payload if isinstance(payload, list) else payload.get("questions", [])
                except Exception as e:
                    log.warning("failed to read questions.json for %s: %s", title, e)
                    questions = []

                for q in questions:
                    try:
                        canvas.post(
                            f"/api/v1/courses/{target_course_id}/quizzes/{new_id}/questions",
                            json={"question": q},
                        )
                        counters["questions"] += 1
                    except Exception as e:
                        log.warning("failed to create question for quiz=%s: %s", title, e)

        counters["imported"] += 1

        if limit is not None and counters["imported"] >= limit:
            log.info("IMPORT_QUIZZES_LIMIT=%s reached; stopping early", limit)
            break

    log.info(
        "Quizzes import complete. imported=%d skipped=%d failed=%d total=%d questions=%d",
        counters["imported"], counters["skipped"], counters["failed"], counters["total"], counters["questions"],
    )
    return counters

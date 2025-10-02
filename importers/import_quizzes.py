# importers/import_quizzes.py
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional, Protocol, Tuple

import requests
from logging_setup import get_logger

__all__ = ["import_quizzes"]


class CanvasLike(Protocol):
    session: requests.Session
    api_root: str
    def post(self, endpoint: str, **kwargs) -> requests.Response: ...
    def get(self, endpoint: str, **kwargs) -> Any: ...


# ----------------------- small helpers ----------------------- #

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


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _summarize_error(detail: Any) -> str:
    if isinstance(detail, dict):
        errors = detail.get("errors")
        if errors:
            try:
                return json.dumps(errors)
            except Exception:
                return str(errors)
        try:
            return json.dumps(detail)
        except Exception:
            return str(detail)

    if isinstance(detail, str):
        snippet = detail.strip()
        lower = snippet.lower()
        if "<html" in lower:
            parts: list[str] = []
            title_match = re.search(r"<title[^>]*>\s*(.*?)\s*</title>", snippet, re.I | re.S)
            if title_match:
                parts.append(f"title={_collapse_ws(title_match.group(1))}")
            h1_match = re.search(r"<h1[^>]*>\s*(.*?)\s*</h1>", snippet, re.I | re.S)
            if h1_match:
                parts.append(f"h1={_collapse_ws(h1_match.group(1))}")
            if not parts:
                text_only = re.sub(r"<[^>]+>", " ", snippet)
                parts.append(_collapse_ws(text_only)[:160])
            return "; ".join(parts)
        return _collapse_ws(snippet)[:200]

    return str(detail)


_QUESTION_DROP_KEYS = {
    "id",
    "quiz_id",
    "assessment_question_id",
    "position",
    "quiz_group_id",
    "matches",
    "migration_id",
    "quiz_version",
    "question_bank_id",
    "question_number",
}

_ANSWER_DROP_KEYS = {
    "id",
    "migration_id",
    "position",
    "assessment_question_id",
    "quiz_id",
}


def _sanitize_question_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    cleaned: Dict[str, Any] = {}
    for key, value in raw.items():
        if key in _QUESTION_DROP_KEYS:
            continue
        cleaned[key] = value

    answers = cleaned.get("answers")
    if isinstance(answers, list):
        new_answers = []
        for ans in answers:
            if not isinstance(ans, dict):
                continue
            ans_clean: Dict[str, Any] = {}
            for key, value in ans.items():
                if key in _ANSWER_DROP_KEYS:
                    continue
                ans_clean[key] = value
            if "answer_text" not in ans_clean and "text" in ans_clean:
                ans_clean["answer_text"] = ans_clean.pop("text")
            new_answers.append(ans_clean)
        cleaned["answers"] = new_answers

    if cleaned.get("question_type") == "matching_question":
        matches = raw.get("matches")
        if isinstance(matches, list):
            cleaned["matches"] = matches

    for field in ["correct_comments", "incorrect_comments", "neutral_comments"]:
        if cleaned.get(field) is None:
            cleaned.pop(field, None)

    return cleaned

def _resp_json(resp: Any) -> dict:
    """
    Be tolerant of various test doubles:
    - requests.Response with .json() / .text / _content
    - dict-like objects
    """
    # Normal path
    if hasattr(resp, "json") and callable(getattr(resp, "json", None)):
        try:
            j = resp.json()
            if isinstance(j, dict):
                return j
        except Exception:
            pass

    # Sometimes a dict is stashed directly
    maybe_dict = getattr(resp, "json", None)
    if isinstance(maybe_dict, dict):
        return maybe_dict

    # Try .text
    text = getattr(resp, "text", None)
    if isinstance(text, str) and text:
        try:
            j = json.loads(text)
            if isinstance(j, dict):
                return j
        except Exception:
            pass

    # Raw bytes
    raw = getattr(resp, "_content", None)
    if isinstance(raw, (bytes, bytearray)) and raw:
        try:
            j = json.loads(raw.decode("utf-8", errors="ignore"))
            if isinstance(j, dict):
                return j
        except Exception:
            pass

    # Already a dict?
    if isinstance(resp, dict):
        return resp

    return {}

def _abs_endpoint(api_root: str, endpoint_path: str) -> str:
    root = api_root.rstrip("/")
    ep = endpoint_path if endpoint_path.startswith("/") else ("/" + endpoint_path)
    return f"{root}{ep}"

def _follow_location_for_id(canvas: CanvasLike, loc_url: str) -> Tuple[Optional[int], dict]:
    """
    Follow a Location header to get the canonical object; return (id, body).
    """
    try:
        r = canvas.session.get(loc_url)
        r.raise_for_status()
        body = _resp_json(r)
        return (_coerce_int(body.get("id")), body)
    except Exception:
        return (None, {})

def _pick_desc_html(dir_: Path, meta: Dict[str, Any]) -> str:
    rel = meta.get("html_path")
    candidates = [rel] if rel else []
    candidates += ["description.html", "index.html", "body.html", "overview.html"]
    for name in candidates:
        if not name:
            continue
        p = dir_ / name
        if p.exists():
            txt = _read_text_if_exists(p)
            return txt or ""
    return ""


# ----------------------- main importer ----------------------- #

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
      • If body lacks id but Location header present, follow it to fetch id
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

    # Absolute endpoint base (so requests_mock matches exactly)
    api_root = (getattr(canvas, "api_root", "") or "").rstrip("/")
    if not api_root.endswith("/api/v1"):
        api_root = f"{api_root}/api/v1"
    abs_create_base = f"{api_root}/courses/{target_course_id}/quizzes"

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
        # Pass-through optional fields commonly present in exports
        for k in [
            "quiz_type", "time_limit", "shuffle_answers", "hide_results",
            "one_question_at_a_time", "cant_go_back", "allowed_attempts",
            "scoring_policy", "show_correct_answers", "due_at", "lock_at", "unlock_at",
            "points_possible"
        ]:
            if meta.get(k) is not None:
                quiz[k] = meta[k]

        old_id = _coerce_int(meta.get("id"))

        existing_new_id = None
        if old_id is not None:
            existing_new_id = id_map.get("quizzes", {}).get(old_id)

        try:
            start_time = time.time()
            if existing_new_id:
                endpoint = f"{abs_create_base}/{existing_new_id}"
                log.debug("update quiz title=%r endpoint=%s", title, endpoint)
                resp = canvas.session.put(endpoint, json={"quiz": quiz})
            else:
                log.debug("create quiz title=%r endpoint=%s", title, abs_create_base)
                resp = canvas.session.post(abs_create_base, json={"quiz": quiz})
            log.debug(
                "quiz %s complete title=%r status=%s duration=%.2fs",
                "PUT" if existing_new_id else "POST",
                title,
                getattr(resp, "status_code", "?"),
                time.time() - start_time,
            )
        except Exception as e:
            counters["failed"] += 1
            log.exception("failed-create title=%s: %s", title, e)
            continue

        status_code = getattr(resp, "status_code", 200)
        if status_code >= 400:
            detail_raw = _resp_json(resp) or getattr(resp, "text", "")
            detail = _summarize_error(detail_raw)
            counters["failed"] += 1
            log.error(
                "failed-create status=%s title=%s detail=%s",
                status_code,
                title,
                detail,
            )
            continue

        body = _resp_json(resp)
        new_id = _coerce_int(body.get("id"))

        if new_id is None and existing_new_id:
            new_id = existing_new_id

        if new_id is None:
            loc = getattr(resp, "headers", {}).get("Location")
            if loc:
                new_id, body2 = _follow_location_for_id(canvas, loc)
                if new_id is None:
                    body = body2 or body  # keep whatever we got
            # else: stay None

        if new_id is None:
            counters["failed"] += 1
            log.error(
                "failed-create (no id) title=%s detail=%s",
                title,
                _summarize_error(body),
            )
            continue

        # Map old->new when possible
        if old_id is not None:
            id_map["quizzes"][old_id] = new_id

        # Optional: create questions
        if include_questions:
            q_json = item / "questions.json"
            if q_json.exists():
                try:
                    payload = _read_json(q_json)
                    questions = payload if isinstance(payload, list) else payload.get("questions", [])
                except Exception as e:
                    log.warning("failed to read questions.json for %s: %s", title, e)
                    questions = []

                if new_id and existing_new_id:
                    try:
                        list_url = f"{abs_create_base}/{new_id}/questions"
                        existing_q = canvas.session.get(list_url, params={"per_page": 100}).json()
                        if isinstance(existing_q, list):
                            for eq in existing_q:
                                eq_id = eq.get("id")
                                if eq_id:
                                    del_url = f"{abs_create_base}/{new_id}/questions/{eq_id}"
                                    canvas.session.delete(del_url)
                    except Exception as e:
                        log.warning("failed to clear existing questions for quiz=%s: %s", title, e)

                questions_url = f"{abs_create_base}/{new_id}/questions"
                for q in questions:
                    if not isinstance(q, dict):
                        continue
                    sanitized = _sanitize_question_payload(q)
                    try:
                        q_start = time.time()
                        resp_q = canvas.session.post(questions_url, json={"question": sanitized})
                        status_q = getattr(resp_q, "status_code", 200)
                        if status_q >= 400:
                            log.warning(
                                "failed to create question quiz=%s status=%s detail=%s",
                                title,
                                status_q,
                                _summarize_error(resp_q),
                            )
                            continue
                        counters["questions"] += 1
                        log.debug(
                            "question POST complete quiz=%s status=%s duration=%.2fs",
                            title,
                            status_q,
                            time.time() - q_start,
                        )
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

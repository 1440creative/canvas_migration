# canvas_calibrator/parsers/items_reader.py
"""
Read quiz questions directly from the New Quizzes Items API.

Replaces the QTI-export + QTI-parse approach with a direct API call:
  GET /api/quiz/v1/courses/{course_id}/quizzes/{quiz_id}/items

Returns a list of question dicts in the same format as qti_parser.py:
  {
      "quiz_title":         str,
      "question_number":    int,
      "stem":               str,
      "definition":         str,   # same as stem for fill-in-blank
      "choices":            list[dict],   # [{id, text}]
      "correct_answer":     str,
      "correct_answer_id":  str | None,
      "question_type":      str,   # NQ slug or mapped name
      "source_quiz_id":     str,
  }
"""
from __future__ import annotations

import logging
import re
from html import unescape
from typing import Any

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _strip_html(html: str) -> str:
    """Very simple HTML → plain text."""
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _li_texts(html: str) -> list[str]:
    """Extract <li>…</li> inner texts in order."""
    return [_strip_html(m) for m in re.findall(r"<li[^>]*>(.*?)</li>", html, re.DOTALL)]


# ---------------------------------------------------------------------------
# Per-type parsers
# ---------------------------------------------------------------------------

def _parse_rich_fill_blank(entry: dict, quiz_title: str, base_q: int, quiz_id: str) -> list[dict]:
    """
    One canvas item → one question per blank.

    scoring_data.value = [{id: blank_uuid, scoring_data: {blank_text: answer}}, ...]
    scoring_data.working_item_body = HTML where each answer is wrapped in backticks
    """
    questions: list[dict] = []
    sd = entry.get("scoring_data", {})
    if not isinstance(sd, dict):
        return questions

    blanks = sd.get("value", [])          # list of {id, scoring_data: {blank_text}}
    working_body = sd.get("working_item_body", "")
    li_texts = _li_texts(working_body)

    # Build a map: blank_uuid → correct_answer
    blank_answers: dict[str, str] = {}
    for b in blanks:
        if isinstance(b, dict):
            bid = b.get("id", "")
            ans = (b.get("scoring_data") or {}).get("blank_text") or ""
            blank_answers[bid] = ans

    # Try to match each blank to a <li> via backtick pattern
    # working_item_body has answers wrapped as `answer text`
    matched_lis: set[int] = set()

    for i, (blank_id, answer) in enumerate(blank_answers.items()):
        stem = ""
        correct_answer = answer

        # Find the <li> containing this answer in backticks
        backtick_pattern = re.escape(f"`{answer}`")
        for j, li in enumerate(li_texts):
            if j in matched_lis:
                continue
            if f"`{answer}`" in li:
                # Replace backtick-wrapped answer with ___
                stem = re.sub(re.escape(f"`{answer}`"), "___", li).strip()
                matched_lis.add(j)
                break

        if not stem:
            # Fallback: use the whole working_body as stem context
            stem = correct_answer

        questions.append({
            "quiz_title": quiz_title,
            "question_number": base_q + i + 1,
            "stem": stem,
            "definition": stem,
            "choices": [],
            "correct_answer": correct_answer,
            "correct_answer_id": blank_id,
            "question_type": "fill_in_multiple_blanks_question",
            "source_quiz_id": quiz_id,
        })

    return questions


def _parse_choice(entry: dict, quiz_title: str, q_num: int, quiz_id: str) -> list[dict]:
    """
    Multiple-choice (and true-false when it has choices).

    interaction_data.choices = [{id, item_body}, ...]
    scoring_data.value = correct choice UUID  (or for true-false: true/false bool)
    """
    stem = _strip_html(entry.get("item_body", ""))
    idata = entry.get("interaction_data", {})
    choices_raw = idata.get("choices", []) or []

    sd = entry.get("scoring_data", {}) or {}
    correct_id = sd.get("value")

    choices = [{"id": c.get("id", ""), "text": _strip_html(c.get("item_body", ""))}
               for c in choices_raw]

    correct_text = ""
    for c in choices:
        if c["id"] == correct_id:
            correct_text = c["text"]
            break

    return [{
        "quiz_title": quiz_title,
        "question_number": q_num,
        "stem": stem,
        "definition": stem,
        "choices": choices,
        "correct_answer": correct_text,
        "correct_answer_id": str(correct_id) if correct_id else None,
        "question_type": "multiple_choice_question",
        "source_quiz_id": quiz_id,
    }]


def _parse_true_false(entry: dict, quiz_title: str, q_num: int, quiz_id: str) -> list[dict]:
    """
    True/false: scoring_data.value is a bool.
    """
    stem = _strip_html(entry.get("item_body", ""))
    sd = entry.get("scoring_data", {}) or {}
    value = sd.get("value")
    correct_answer = "True" if value is True else ("False" if value is False else str(value))

    return [{
        "quiz_title": quiz_title,
        "question_number": q_num,
        "stem": stem,
        "definition": stem,
        "choices": [{"id": "true", "text": "True"}, {"id": "false", "text": "False"}],
        "correct_answer": correct_answer,
        "correct_answer_id": str(value).lower() if isinstance(value, bool) else None,
        "question_type": "true_false_question",
        "source_quiz_id": quiz_id,
    }]


def _parse_categorization(entry: dict, quiz_title: str, base_q: int, quiz_id: str) -> list[dict]:
    """
    Categorization: one sub-question per category.

    interaction_data.categories = {uuid: {item_body: label}}
    interaction_data.answers    = could be a dict or list of answer items
    scoring_data.value = [{id: cat_uuid, scoring_data: {value: [answer_uuids]}}]
    """
    questions: list[dict] = []
    idata = entry.get("interaction_data", {}) or {}
    cats = idata.get("categories", {}) or {}
    answers_raw = idata.get("answers", {}) or {}

    # answers may be dict {uuid: {item_body}} or list
    if isinstance(answers_raw, dict):
        answers_map: dict[str, str] = {k: _strip_html(v.get("item_body", "")) for k, v in answers_raw.items()}
    else:
        answers_map = {a.get("id", ""): _strip_html(a.get("item_body", "")) for a in (answers_raw or [])}

    sd = entry.get("scoring_data", {}) or {}
    sd_list = sd.get("value", []) if isinstance(sd, dict) else []

    # Build cat_uuid → list of correct answer texts
    cat_correct: dict[str, list[str]] = {}
    for entry_sd in (sd_list or []):
        if not isinstance(entry_sd, dict):
            continue
        cat_id = entry_sd.get("id", "")
        ans_ids = (entry_sd.get("scoring_data") or {}).get("value", [])
        cat_correct[cat_id] = [answers_map.get(aid, aid) for aid in (ans_ids or [])]

    stem_base = _strip_html(entry.get("item_body", "") or "")

    for i, (cat_id, cat_info) in enumerate(cats.items()):
        cat_label = _strip_html(cat_info.get("item_body", "")) if isinstance(cat_info, dict) else str(cat_info)
        correct_texts = cat_correct.get(cat_id, [])
        correct_answer = "; ".join(correct_texts) if correct_texts else ""

        stem = f"Category: {cat_label}" + (f" — {stem_base}" if stem_base else "")

        questions.append({
            "quiz_title": quiz_title,
            "question_number": base_q + i + 1,
            "stem": stem,
            "definition": stem,
            "choices": [],
            "correct_answer": correct_answer,
            "correct_answer_id": cat_id,
            "question_type": "categorization_question",
            "source_quiz_id": quiz_id,
        })

    return questions


# ---------------------------------------------------------------------------
# Item dispatcher
# ---------------------------------------------------------------------------

def _parse_item(item: dict, quiz_title: str, q_num: int, quiz_id: str) -> list[dict]:
    """Dispatch a single quiz item to the appropriate parser."""
    entry_type = item.get("entry_type", "")
    if entry_type == "Stimulus":
        return []  # passage/scenario, not a question

    entry = item.get("entry") or {}
    slug = entry.get("interaction_type_slug", "")

    if slug == "rich-fill-blank":
        return _parse_rich_fill_blank(entry, quiz_title, q_num - 1, quiz_id)
    elif slug == "choice":
        return _parse_choice(entry, quiz_title, q_num, quiz_id)
    elif slug == "true-false":
        return _parse_true_false(entry, quiz_title, q_num, quiz_id)
    elif slug == "categorization":
        return _parse_categorization(entry, quiz_title, q_num - 1, quiz_id)
    else:
        log.debug("Skipping unsupported item type: %r (entry_type=%r)", slug, entry_type)
        return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_quiz_questions(
    course_id: int | str,
    api,                # CanvasAPI instance
) -> list[dict]:
    """
    Fetch all quiz questions for a course via the New Quizzes Items API.

    Args:
        course_id:  Canvas course ID
        api:        CanvasAPI instance pointing at the target Canvas server

    Returns:
        List of question dicts (same format as qti_parser.parse_qti_zip)
    """
    from canvas_calibrator.exporters.new_quizzes_exporter import _quiz_url

    # 1. List all quizzes
    quizzes_resp = api._request(
        "GET",
        _quiz_url(api, f"/api/quiz/v1/courses/{course_id}/quizzes"),
        params={"per_page": 100},
    )
    quizzes = quizzes_resp.json()
    if not isinstance(quizzes, list):
        log.error("Unexpected quiz list response: %r", quizzes)
        return []

    log.info("Fetched %d quizzes for course %s", len(quizzes), course_id)
    all_questions: list[dict] = []

    for quiz in quizzes:
        quiz_id = str(quiz.get("id", ""))
        quiz_title = quiz.get("title") or f"Quiz {quiz_id}"

        # 2. Fetch items for this quiz
        items_resp = api._request(
            "GET",
            _quiz_url(api, f"/api/quiz/v1/courses/{course_id}/quizzes/{quiz_id}/items"),
            params={"per_page": 100},
        )
        items = items_resp.json()
        if not isinstance(items, list):
            log.warning("Unexpected items response for quiz %s: %r", quiz_id, items)
            continue

        q_num = 1
        quiz_qs: list[dict] = []
        for item in items:
            parsed = _parse_item(item, quiz_title, q_num, quiz_id)
            quiz_qs.extend(parsed)
            q_num += len(parsed)

        log.info("Quiz %s (%s): %d items → %d questions",
                 quiz_id, quiz_title[:50], len(items), len(quiz_qs))
        all_questions.extend(quiz_qs)

    log.info("Total questions fetched: %d", len(all_questions))
    return all_questions

# canvas_calibrator/parsers/qti_parser.py
"""
Parse a New Quizzes QTI zip into a list of question dicts.

Supported types:
  - fill_in_multiple_blanks_question  → one item per blank
  - multiple_choice_question
  - true_false_question

QTI zip layout:
  {hash}/
    {hash}.xml            (question items)
    assessment_meta.xml   (quiz title)

Note: the hash directory may have a leading 'g' prefix (e.g. g54e8a1bd4...).
The questions XML filename matches its parent directory name exactly.
"""
from __future__ import annotations

import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

class _StripHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts).strip()


def _strip_html(html: str) -> str:
    p = _StripHTML()
    p.feed(html)
    return p.get_text()


def _extract_li_items(html: str) -> list[str]:
    """Return plain-text content of each <li> in html (non-nested)."""
    items = re.findall(r"<li[^>]*>(.*?)</li>", html, re.DOTALL | re.IGNORECASE)
    return [_strip_html(item).strip() for item in items]


# ---------------------------------------------------------------------------
# XML namespace handling
# ---------------------------------------------------------------------------

def _tag(elem: ET.Element) -> str:
    """Return local tag name (strips namespace URI if present)."""
    tag = elem.tag
    if tag.startswith("{"):
        tag = tag.split("}", 1)[1]
    return tag


def _find(elem: ET.Element, *path: str) -> ET.Element | None:
    """Namespace-agnostic single-level find via direct children."""
    cur: ET.Element | None = elem
    for part in path:
        if cur is None:
            return None
        cur = next((c for c in cur if _tag(c) == part), None)
    return cur


def _findall(elem: ET.Element, tag: str) -> list[ET.Element]:
    return [c for c in elem.iter() if _tag(c) == tag]


# ---------------------------------------------------------------------------
# Quiz title
# ---------------------------------------------------------------------------

def _parse_quiz_title(tree: ET.ElementTree) -> str:
    root = tree.getroot()
    # Try <assessment title="..."> attribute first (present in real zips)
    for elem in root.iter():
        if _tag(elem) == "assessment":
            t = elem.get("title", "").strip()
            if t:
                return t
    # Fallback: <title> element
    title_elem = next((c for c in root.iter() if _tag(c) == "title"), None)
    if title_elem is not None and title_elem.text:
        return title_elem.text.strip()
    return "Unknown Quiz"


# ---------------------------------------------------------------------------
# Correct-answer resolution from <resprocessing>
# ---------------------------------------------------------------------------

def _correct_idents(item: ET.Element) -> dict[str, str]:
    """
    Return {response_ident: correct_answer_ident} from <resprocessing>.

    Accepts both action="Set" and action="Add" — any positive setvar value
    is treated as a correct-answer marker (New Quizzes uses action="Add").
    """
    mapping: dict[str, str] = {}
    for respcondition in _findall(item, "respcondition"):
        setvar = next(
            (c for c in respcondition.iter() if _tag(c) == "setvar"), None
        )
        if setvar is None:
            continue
        try:
            val = float(setvar.text or "0")
        except ValueError:
            val = 0.0
        if val <= 0:
            continue
        varequal = next(
            (c for c in respcondition.iter() if _tag(c) == "varequal"), None
        )
        if varequal is None:
            continue
        resp_ident = varequal.get("respident", "")
        answer_ident = (varequal.text or "").strip()
        if resp_ident and answer_ident:
            mapping[resp_ident] = answer_ident
    return mapping


# ---------------------------------------------------------------------------
# Answer text lookup
# ---------------------------------------------------------------------------

def _choice_texts(response_lid: ET.Element) -> dict[str, str]:
    """Return {ident: text} for all <response_label> children."""
    result: dict[str, str] = {}
    for label in _findall(response_lid, "response_label"):
        ident = label.get("ident", "")
        mattext = next(
            (c for c in label.iter() if _tag(c) == "mattext"), None
        )
        text = ""
        if mattext is not None and mattext.text:
            text = _strip_html(mattext.text)
        result[ident] = text
    return result


# ---------------------------------------------------------------------------
# Stem extraction — direct path: presentation > material > mattext
# ---------------------------------------------------------------------------

def _stem_html(item: ET.Element) -> str:
    """
    Extract stem HTML from <presentation><material><mattext>.

    Uses a direct child-walk rather than iter() to avoid picking up
    mattext nodes from nested <response_lid> elements.
    """
    presentation = _find(item, "presentation")
    if presentation is None:
        return ""
    material = _find(presentation, "material")
    if material is None:
        return ""
    mattext = _find(material, "mattext")
    if mattext is not None and mattext.text:
        return mattext.text
    return ""


def _stem_plain(item: ET.Element) -> str:
    return _strip_html(_stem_html(item))


# ---------------------------------------------------------------------------
# Per-type parsers
# ---------------------------------------------------------------------------

def _parse_multiple_choice(
    item: ET.Element,
    quiz_title: str,
    question_index: int,
    source_zip: str,
    question_type: str = "multiple_choice",
) -> dict[str, Any]:
    stem = _stem_plain(item)
    correct_map = _correct_idents(item)

    response_lids = _findall(item, "response_lid")
    choices: list[str] = []
    correct_answer = ""

    if response_lids:
        rl = response_lids[0]
        resp_ident = rl.get("ident", "")
        choice_map = _choice_texts(rl)
        choices = list(choice_map.values())
        correct_ident = correct_map.get(resp_ident, "")
        correct_answer = choice_map.get(correct_ident, "")

    return {
        "quiz_title": quiz_title,
        "question_index": question_index,
        "question_type": question_type,
        "stem": stem,
        "definition": "",
        "correct_answer": correct_answer,
        "choices": choices,
        "source_quiz_zip": source_zip,
    }


def _parse_fill_in_blanks(
    item: ET.Element,
    quiz_title: str,
    base_index: int,
    source_zip: str,
) -> list[dict[str, Any]]:
    """
    Emit one question dict per blank.

    Stem HTML contains [uuid] placeholders (without 'response_' prefix).
    response_lid idents are 'response_{uuid}'.

    For each blank:
      - Strip 'response_' prefix from ident to get the uuid.
      - Find the <li> in the stem that contains [{uuid}].
      - Extract that sentence as the definition, replacing [{uuid}] with ___.
    Word bank = all choices across all blanks (shared pool).
    """
    stem_html = _stem_html(item)
    stem_plain = _strip_html(stem_html)
    correct_map = _correct_idents(item)
    response_lids = _findall(item, "response_lid")

    # Build word bank: union of all choices (all blanks share the same pool)
    word_bank_map: dict[str, str] = {}
    for rl in response_lids:
        word_bank_map.update(_choice_texts(rl))
    word_bank = list(word_bank_map.values())

    # Pre-extract <li> sentences from stem HTML for definition lookup
    li_items = _extract_li_items(stem_html)

    results: list[dict[str, Any]] = []
    for offset, rl in enumerate(response_lids):
        resp_ident = rl.get("ident", "")  # e.g. "response_b7230ac9-..."

        # Strip 'response_' prefix to get the bare uuid used in stem placeholders
        uuid = resp_ident.removeprefix("response_")

        choice_map = _choice_texts(rl)
        correct_ident = correct_map.get(resp_ident, "")
        correct_answer = choice_map.get(correct_ident, "")

        # Find the <li> that contains this blank's [uuid] placeholder
        placeholder = f"[{uuid}]"
        definition = ""
        for li_text in li_items:
            if placeholder in li_text:
                definition = li_text.replace(placeholder, "___")
                break

        # Fallback: replace placeholder in full stem plain text
        if not definition:
            definition = stem_plain.replace(placeholder, "___")

        results.append({
            "quiz_title": quiz_title,
            "question_index": base_index + offset,
            "question_type": "fill_in_blank",
            "stem": stem_plain,
            "definition": definition,
            "correct_answer": correct_answer,
            "choices": word_bank,
            "source_quiz_zip": source_zip,
        })

    return results


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def parse_qti_zip(zip_path: str | Path) -> list[dict[str, Any]]:
    """
    Parse a New Quizzes QTI zip.

    Returns a list of question dicts ordered by their position in the quiz.
    The zip structure is auto-detected: the questions XML is the file whose
    basename (without .xml) matches its parent directory name.
    """
    zip_path = Path(zip_path)
    source_zip = zip_path.name

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()

        questions_xml = ""
        meta_xml = ""
        for name in names:
            parts = name.split("/")
            if len(parts) == 2 and parts[1].endswith(".xml"):
                stem = parts[1][:-4]  # strip .xml
                if stem == parts[0]:  # filename matches directory name
                    questions_xml = name
            if name.endswith("assessment_meta.xml"):
                meta_xml = name

        if not questions_xml:
            raise ValueError(f"Could not locate questions XML in {zip_path.name}")

        # Parse quiz title from assessment_meta.xml
        quiz_title = "Unknown Quiz"
        if meta_xml:
            with zf.open(meta_xml) as f:
                try:
                    quiz_title = _parse_quiz_title(ET.parse(f))
                except ET.ParseError:
                    pass

        # Parse questions XML
        with zf.open(questions_xml) as f:
            tree = ET.parse(f)

    root = tree.getroot()
    items = _findall(root, "item")

    questions: list[dict[str, Any]] = []
    question_index = 0

    for item in items:
        # Read question_type from <itemmetadata><qtimetadata><qtimetadatafield>
        qtype_raw = ""
        for qtmd in _findall(item, "qtimetadatafield"):
            label = next((c for c in qtmd if _tag(c) == "fieldlabel"), None)
            entry = next((c for c in qtmd if _tag(c) == "fieldentry"), None)
            if label is not None and (label.text or "").strip() == "question_type":
                qtype_raw = (entry.text or "").strip() if entry is not None else ""
                break

        if qtype_raw in ("multiple_choice_question", "true_false_question"):
            qtype = "true_false" if qtype_raw == "true_false_question" else "multiple_choice"
            questions.append(
                _parse_multiple_choice(item, quiz_title, question_index, source_zip, qtype)
            )
            question_index += 1

        elif qtype_raw == "fill_in_multiple_blanks_question":
            blanks = _parse_fill_in_blanks(item, quiz_title, question_index, source_zip)
            questions.extend(blanks)
            question_index += len(blanks)

        # Unknown types are silently skipped

    return questions

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


# UUID pattern used as [uuid] placeholders in FIMB stems
_UUID_RE = re.compile(
    r"\[([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\]",
    re.IGNORECASE,
)


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
    """Namespace-agnostic find via iteration."""
    cur: ET.Element | None = elem
    for part in path:
        if cur is None:
            return None
        cur = next((c for c in cur if _tag(c) == part), None)
    return cur


def _findall(elem: ET.Element, tag: str) -> list[ET.Element]:
    return [c for c in elem.iter() if _tag(c) == tag]


# ---------------------------------------------------------------------------
# Quiz title from assessment_meta.xml
# ---------------------------------------------------------------------------

def _parse_quiz_title(tree: ET.ElementTree) -> str:
    root = tree.getroot()
    # <title> or <assessment title="...">
    title_elem = next((c for c in root.iter() if _tag(c) == "title"), None)
    if title_elem is not None and title_elem.text:
        return title_elem.text.strip()
    if root.get("title"):
        return root.get("title", "").strip()
    return "Unknown Quiz"


# ---------------------------------------------------------------------------
# Correct-answer resolution from <resprocessing>
# ---------------------------------------------------------------------------

def _correct_idents(item: ET.Element) -> dict[str, str]:
    """
    Return {response_ident: correct_answer_ident} from <resprocessing>.
    Works for both MC/TF (single resprocessing) and FIMB (one per response_lid).
    """
    mapping: dict[str, str] = {}
    for respcondition in _findall(item, "respcondition"):
        # Only look at conditions with setvar action="Set" value > 0 (correct)
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
        # Find conditionvar > varequal
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
# Answer text lookup from <response_lid> / <response_str>
# ---------------------------------------------------------------------------

def _choice_texts(response_lid: ET.Element) -> dict[str, str]:
    """Return {ident: text} for all <response_label> children."""
    result: dict[str, str] = {}
    for label in _findall(response_lid, "response_label"):
        ident = label.get("ident", "")
        # text may be in <material><mattext>
        mattext = next(
            (c for c in label.iter() if _tag(c) == "mattext"), None
        )
        text = ""
        if mattext is not None and mattext.text:
            text = _strip_html(mattext.text)
        result[ident] = text
    return result


def _stem_html(item: ET.Element) -> str:
    """Extract the stem HTML from <presentation><material><mattext>."""
    presentation = _find(item, "presentation")
    if presentation is None:
        return ""
    for mattext in _findall(presentation, "mattext"):
        parent_tags = {_tag(p) for p in item.iter()}
        # Grab the first mattext that is directly under material (not inside response_label)
        text = mattext.text or ""
        if text.strip():
            return text
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

    # Find the single response_lid
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

    The stem HTML contains [uuid] placeholders. For each response_lid:
      - Replace that uuid in the stem with ___ to get the definition sentence.
      - The word bank = all choices across all response_lids (union, deduped).
    """
    stem_html = _stem_html(item)
    correct_map = _correct_idents(item)
    response_lids = _findall(item, "response_lid")

    # Build word bank: union of all choices across all blanks
    word_bank_map: dict[str, str] = {}  # ident -> text
    for rl in response_lids:
        word_bank_map.update(_choice_texts(rl))
    word_bank = list(word_bank_map.values())

    results: list[dict[str, Any]] = []
    for offset, rl in enumerate(response_lids):
        resp_ident = rl.get("ident", "")
        choice_map = _choice_texts(rl)
        correct_ident = correct_map.get(resp_ident, "")
        correct_answer = choice_map.get(correct_ident, "")

        # Build definition: replace THIS blank's uuid with ___, strip others
        def_html = stem_html
        for other_rl in response_lids:
            other_ident = other_rl.get("ident", "")
            if other_ident == resp_ident:
                def_html = def_html.replace(f"[{resp_ident}]", "___")
            else:
                # Replace other blanks with their correct answer text for context
                other_correct_ident = correct_map.get(other_ident, "")
                other_text = _choice_texts(other_rl).get(other_correct_ident, f"[{other_ident}]")
                def_html = def_html.replace(f"[{other_ident}]", other_text)

        definition = _strip_html(def_html)

        results.append({
            "quiz_title": quiz_title,
            "question_index": base_index + offset,
            "question_type": "fill_in_blank",
            "stem": _strip_html(stem_html),
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
    """
    zip_path = Path(zip_path)
    source_zip = zip_path.name

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()

        # Detect hash directory dynamically
        # Structure: {hash}/{hash}.xml  and  {hash}/assessment_meta.xml
        hash_dir = ""
        questions_xml = ""
        meta_xml = ""
        for name in names:
            parts = name.split("/")
            if len(parts) == 2 and parts[1].endswith(".xml") and parts[1] != "assessment_meta.xml":
                if parts[0] == parts[1].replace(".xml", ""):
                    hash_dir = parts[0]
                    questions_xml = name
            if name.endswith("assessment_meta.xml"):
                meta_xml = name

        if not questions_xml:
            raise ValueError(f"Could not locate questions XML in {zip_path.name}")

        # Parse quiz title
        quiz_title = "Unknown Quiz"
        if meta_xml:
            with zf.open(meta_xml) as f:
                try:
                    meta_tree = ET.parse(f)
                    quiz_title = _parse_quiz_title(meta_tree)
                except ET.ParseError:
                    pass

        # Parse questions
        with zf.open(questions_xml) as f:
            tree = ET.parse(f)

    root = tree.getroot()

    # Collect all <item> elements
    items = _findall(root, "item")

    questions: list[dict[str, Any]] = []
    question_index = 0

    for item in items:
        # Determine question type from <fieldlabel>question_type</fieldlabel>
        qtype_raw = ""
        for field in _findall(item, "fieldentry"):
            parent = next(
                (
                    p for p in root.iter()
                    if any(_tag(c) == "fieldentry" and c is field for c in p)
                ),
                None,
            )
            # Simpler: find fieldlabel sibling
        # Walk itemmetadata
        for qtmd in _findall(item, "qtimetadatafield"):
            label = next((c for c in qtmd if _tag(c) == "fieldlabel"), None)
            entry = next((c for c in qtmd if _tag(c) == "fieldentry"), None)
            if label is not None and (label.text or "").strip() == "question_type":
                qtype_raw = (entry.text or "").strip() if entry is not None else ""
                break

        if qtype_raw in ("multiple_choice_question", "true_false_question"):
            qtype = "true_false" if qtype_raw == "true_false_question" else "multiple_choice"
            q = _parse_multiple_choice(item, quiz_title, question_index, source_zip, qtype)
            questions.append(q)
            question_index += 1

        elif qtype_raw == "fill_in_multiple_blanks_question":
            blanks = _parse_fill_in_blanks(item, quiz_title, question_index, source_zip)
            questions.extend(blanks)
            question_index += len(blanks)

        # Unknown types are skipped

    return questions

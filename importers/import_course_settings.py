# importers/import_course_settings.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import requests
from logging_setup import get_logger

# A conservative allowlist of course fields Canvas accepts on update.
# (Anything else gets ignored rather than 4xx’ing your request.)
_ALLOWED_FIELDS = {
    "name",
    "course_code",
    "start_at",
    "end_at",
    "is_public",
    "is_public_to_auth_users",
    "public_syllabus",
    "public_syllabus_to_auth",
    "public_description",
    "allow_student_wiki_edits",
    "allow_wiki_comments",
    "open_enrollment",
    "self_enrollment",
    "restrict_enrollments_to_course_dates",
    "term_id",
    "license",
    "default_view",
    "time_zone",
    "grading_standard_id",
    "hide_final_grades",
    "apply_assignment_group_weights",
    "blueprint",  # harmless pass-through; ignored since we won't set it
}

def _read_json(p: Path) -> Dict[str, Any]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _filter_course_fields(obj: Dict[str, Any]) -> Dict[str, Any]:
    # Accept either {"course": {...}} or a flat dict exported earlier
    payload = obj.get("course", obj) if isinstance(obj, dict) else {}
    return {k: v for k, v in payload.items() if k in _allowed()}

def _allowed() -> set[str]:
    return set(_ALLOWED_FIELDS)

#syllabus HTML

def import_syllabus_html(*, target_course_id: int, export_root: Path, canvas) -> bool:
    """
    Read course/syllabus.html and update the target course syllabus_body.
    Returns True if updated, False if file missing/empty.
    """
    log = get_logger(artifact="course_settings", course_id=target_course_id)

    path = export_root / "course" / "syllabus.html"
    if not path.exists():
        log.debug("No syllabus.html found; skipping syllabus import")
        return False

    html = path.read_text(encoding="utf-8")
    if not html.strip():
        log.debug("syllabus.html is empty; skipping syllabus import")
        return False

    payload = {"course": {"syllabus_body": html}}
    log.debug("PUT syllabus_body", extra={"bytes": len(html.encode("utf-8"))})

    resp = canvas.put(f"/api/v1/courses/{target_course_id}", json=payload)
    if resp.status_code >= 400:
        # helpful diagnostics
        try:
            body = resp.text[:600]
        except Exception:
            body = "<no body>"
        log.error("Failed to update syllabus: %s %s", resp.status_code, body)
        resp.raise_for_status()

    log.info("Syllabus HTML updated")
    return True


def import_course_settings(
    *,
    target_course_id: int,
    export_root: Path,
    canvas,
) -> None:
    """
    Import core course settings only.
    Note: Blueprint enablement is manual in Canvas UI; importer does not touch it.
    """
    log = get_logger(artifact="course_settings", course_id=target_course_id)

    course_dir = export_root / "course"
    # Accept either name (your export has "course_settings.json")
    candidates = [
        course_dir / "settings.json",
        course_dir / "course_settings.json",
    ]

    settings: Dict[str, Any] = {}
    used_path: Path | None = None
    for p in candidates:
        if p.exists():
            settings = _read_json(p)
            used_path = p
            break

    if not settings:
        log.debug("No settings.json found; skipping settings update")
        log.info("Course settings import complete")
        return

    update = {"course": _filter_course_fields(settings)}
    if not update["course"]:
        log.debug("No allowed course fields to update; skipping PUT")
        log.info("Course settings import complete")
        return

    log.debug(
        "PUT course fields",
        extra={"used": str(used_path), "keys": sorted(update["course"].keys())},
    )
    
   


    resp = canvas.put(f"/api/v1/courses/{target_course_id}", json=update)
    try:
        resp.raise_for_status()
    except requests.HTTPError:
        # Helpful diagnostics
        log.error("Failed to update course fields: %s %s", resp.status_code, resp.text[:600])
        raise
    
     #import syllabus html
    try:
        import_syllabus_html(target_course_id=target_course_id, export_root=export_root, canvas=canvas)
    except Exception as e:
        log = get_logger(artifact="course_settings", course_id=target_course_id)
        log.warning("Syllabus import failed: %s", e)

    log.info("Course settings import complete")

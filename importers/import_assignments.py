# import/import_assignments.py
"""
Import Assignments into a Canvas course using your CanvasAPI-style wrapper.

Expected export layout (per assignment directory):
    assignments/<something>/
      ├─ assignment_metadata.json   # includes id, name/title, points, dates, submission_types, etc.
      └─ (optional) description.html

This importer:
  1) Loads assignment_metadata.json (+ description.html if present).
  2) Creates the assignment via POST /api/v1/courses/{course_id}/assignments.
  3) Records id_map["assignments"][old_id] = new_id.

Notes:
- We pass through only Canvas-accepted fields in the "assignment" envelope.
- Description HTML is taken from file if present; otherwise metadata.get("description").
"""

from __future__ import annotations

import json
import requests
from pathlib import Path
from typing import Dict, Any, Optional, Protocol


from logging_setup import get_logger
from utils.mapping import record_mapping

__all__ = ["import_assignments"]


# ---- Protocol to decouple from your exact CanvasAPI class -------------------
class CanvasLike(Protocol):
    session: requests.Session
    api_root: str  # e.g., "https://school.instructure.com/api/v1/"

    def post(self, endpoint: str, **kwargs) -> requests.Response: ...
    def put(self, endpoint: str, **kwargs) -> requests.Response: ...
    def post_json(self, endpoint: str, *, payload: Dict[str, Any]) -> Dict[str, Any]: ...


# ---- Helpers ----------------------------------------------------------------
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

# Map commonly exported metadata keys to Canvas "assignment" fields.
# Anything not listed here is ignored for safety, but you can extend as needed.
_ALLOWED_FIELDS = {
    # Identity / core
    "name", "position", "published",

    # Points & grading
    "points_possible", "grading_type", "grading_standard_id",

    # Dates (ISO8601 strings expected)
    "due_at", "unlock_at", "lock_at",

    # Submission / workflow
    "submission_types", "allowed_extensions", "peer_reviews",
    "automatic_peer_reviews", "grade_group_students_individually",
    "muted", "omit_from_final_grade", "group_category_id",
    "notify_of_update", "only_visible_to_overrides",

    # Plagiarism / external tools (pass-through if present)
    "turnitin_enabled", "vericite_enabled", "integration_id",
    "external_tool_tag_attributes",  # for LTI: { url, new_tab, resource_link_id, ... }

    # Misc
    "description", "rubric_settings",
    "freeze_on_copy",
}

def _build_assignment_payload(metadata: Dict[str, Any], body_html: Optional[str]) -> Dict[str, Any]:
    # Prefer "name"; fall back to "title"
    name = metadata.get("name") or metadata.get("title")
    payload: Dict[str, Any] = {}

    for k in _ALLOWED_FIELDS:
        if k in metadata and metadata[k] is not None:
            payload[k] = metadata[k]

    # Normalize name/title
    if name:
        payload["name"] = name
        payload.pop("title", None)  # Canvas uses 'name'

    # Prefer file HTML body if provided
    if body_html is not None:
        payload["description"] = body_html
    # else if metadata already had 'description', we left it above

    return {"assignment": payload}


# ---- Public entrypoint ------------------------------------------------------
def import_assignments(
    *,
    target_course_id: int,
    export_root: Path,
    canvas: CanvasLike,
    id_map: Dict[str, Dict[int, int]],
) -> None:
    """
    Create assignments from export_root/assignments into the target course and update id_map.

    Produces/updates:
        id_map["assignments"] : Dict[int(old_assignment_id) -> int(new_assignment_id)]
    """
    logger = get_logger(course_id=target_course_id, artifact="assignments")

    asg_dir = export_root / "assignments"
    if not asg_dir.exists():
        logger.warning("No assignments directory found at %s", asg_dir)
        return

    logger.info("Starting assignments import from %s", asg_dir)

    asg_id_map = id_map.setdefault("assignments", {})
    imported = 0
    skipped = 0
    failed = 0

    for meta_file in asg_dir.rglob("assignment_metadata.json"):
        try:
            meta = _read_json(meta_file)
        except Exception as e:
            failed += 1
            logger.exception("Failed to read %s: %s", meta_file, e)
            continue

        old_id = _coerce_int(meta.get("id"))
        # Resolve HTML description file (optional)
        html_path = meta_file.parent / (meta.get("html_path") or "description.html")

        body_html = _read_text_if_exists(html_path)

        # Canvas requires a name/title; skip if missing
        name = meta.get("name") or meta.get("title")
        if not name:
            skipped += 1
            logger.warning("Skipping %s (missing assignment name/title)", meta_file)
            continue

        try:
            payload = _build_assignment_payload(meta, body_html)
            resp = canvas.post(f"/api/v1/courses/{target_course_id}/assignments", json=payload)
            resp.raise_for_status()
            created = resp.json()

            new_id = _coerce_int(created.get("id"))
            # if old_id is not None and new_id is not None:
            #     asg_id_map[old_id] = new_id
            record_mapping(
                old_id=old_id,
                new_id=new_id,
                old_slug=None,   # assignments don’t have slugs
                new_slug=None,
                id_map=asg_id_map,
                # slug_map={},   handled in mapping.py  # not used for assignments 
            )

            imported += 1
            logger.info("Created assignment '%s' old_id=%s new_id=%s", name, old_id, new_id)

        except Exception as e:
            failed += 1
            logger.exception("Failed to create assignment from %s: %s", meta_file.parent, e)

    logger.info(
        "Assignments import complete. imported=%d skipped=%d failed=%d total=%d",
        imported, skipped, failed, imported + skipped + failed
    )

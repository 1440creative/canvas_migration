# importers/import_rubrics.py
"""
Import course-level rubrics exported to:
    <export_root>/<course_id>/course/rubrics/rubric_*.json

Behavior:
- Idempotent: if a rubric with the same title already exists in the target
  course, do not recreate it — reuse the existing rubric id.
- Builds/updates id_map["rubrics"] with {old_id -> new_id} whenever possible.
- Uses Canvas JSON creation endpoint:
    POST /api/v1/courses/:course_id/rubrics
  with payload:
    {
      "rubric": [ ...criteria... ],
      "title": "...",
      "free_form_criterion_comments": false
    }

Returns a summary dict: {"created": N, "failed": M, "total": T}
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import json
import requests

from logging_setup import get_logger

__all__ = ["import_rubrics"]


def _read_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _coerce_int(x: Any) -> Optional[int]:
    try:
        return int(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def _old_id_from_filename(p: Path) -> Optional[int]:
    """
    Expect filenames like rubric_65123.json; return 65123 when present.
    """
    stem = p.stem  # e.g., "rubric_65123"
    if "_" in stem:
        suffix = stem.split("_", 1)[1]
        return _coerce_int(suffix)
    return None


def _existing_rubrics_by_title(canvas, course_id: int) -> Dict[str, Dict[str, Any]]:
    """
    Return a map: lowercased title -> rubric object (must include 'id').
    """
    try:
        items = canvas.get(f"/api/v1/courses/{course_id}/rubrics")
    except Exception:
        items = []
    out: Dict[str, Dict[str, Any]] = {}
    for r in (items or []):
        title = (r.get("title") or "").strip()
        if title and isinstance(r.get("id"), int):
            out[title.lower()] = r
    return out


def import_rubrics(
    *,
    target_course_id: int,
    export_root: Path,
    canvas,
    id_map: Optional[Dict[str, Dict[Any, Any]]] = None,
) -> Dict[str, int]:
    """
    Create (or reuse) rubrics in the target course from exported JSON files.

    Args:
        target_course_id: numeric Canvas course id on the TARGET instance
        export_root: path like ".../<source_course_id>"
        canvas: your CanvasAPI-like client
        id_map: optional shared id_map dict to be updated (adds "rubrics" bucket)

    Returns:
        {"created": int, "failed": int, "total": int}
    """
    log = get_logger(artifact="rubrics_import", course_id=target_course_id)
    out = {"created": 0, "failed": 0, "total": 0}

    rubrics_dir = export_root / "course" / "rubrics"
    if not rubrics_dir.exists():
        log.info("No rubrics to import (missing %s)", rubrics_dir)
        return out

    # Ensure id_map bucket exists
    if id_map is not None:
        id_map.setdefault("rubrics", {})

    # Cache of existing rubrics (for idempotency)
    by_title = _existing_rubrics_by_title(canvas, target_course_id)

    # Iterate all rubric files
    files = sorted(rubrics_dir.glob("rubric_*.json"))
    for jf in files:
        out["total"] += 1
        try:
            data = _read_json(jf)
            title = (data.get("title") or "").strip()
            if not title:
                raise ValueError(f"{jf.name} has no 'title'")

            old_id = _old_id_from_filename(jf)
            if old_id is None:
                old_id = _coerce_int(data.get("id"))

            # Idempotency: if a rubric with the same title already exists, reuse it
            existing = by_title.get(title.lower())
            if existing and isinstance(existing.get("id"), int):
                new_id = int(existing["id"])
                if id_map is not None and old_id is not None:
                    id_map["rubrics"][old_id] = new_id
                log.info("Rubric already exists: %s (id=%s) — skipping create", title, new_id)
                continue

            # Prepare payload (Canvas accepts a simplified JSON structure)
            criteria = data.get("rubric") or data.get("criteria") or []
            payload = {
                "rubric": criteria,
                "title": title,
                "free_form_criterion_comments": bool(data.get("free_form_criterion_comments", False)),
            }

            # Create rubric
            res = canvas.post_json(f"/api/v1/courses/{target_course_id}/rubrics", payload=payload)

            # Canvas typically returns a rubric object with "id" (or nested)
            new_id = res.get("id") or (res.get("rubric") or {}).get("id")
            if not isinstance(new_id, int):
                raise RuntimeError("Create rubric did not return an id")

            # Record mapping and update cache
            if id_map is not None and old_id is not None:
                id_map["rubrics"][old_id] = int(new_id)
            by_title[title.lower()] = {"id": int(new_id), "title": title}

            log.info("Created rubric (form): %s", title)
            out["created"] += 1

        except requests.HTTPError as e:
            status = getattr(e.response, "status_code", None)
            body = e.response.text[:600] if getattr(e, "response", None) is not None else ""
            log.exception("Failed to create rubric from %s: %s %s", jf.name, status, body)
            out["failed"] += 1
        except Exception as e:
            log.exception("Failed to create rubric from %s: %s", jf.name, e)
            out["failed"] += 1

    log.info(
        "Rubrics import complete. created=%d failed=%d total=%d",
        out["created"],
        out["failed"],
        out["total"],
    )
    return out

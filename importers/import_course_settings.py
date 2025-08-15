# importers/import_course_settings.py
"""
Apply course-level metadata and settings to a Canvas course, including optional Blueprint flags.

Expected export layout:
  course/
    ├─ course_metadata.json   # { "id": <old_id>, "name": "...", "course_code": "...", "blueprint": true, ...,
    │                         #   "settings": { ... } }
    └─ (optional) settings.json  # alternative or additional settings; merged over metadata.settings

Operations:
  1) PUT /api/v1/courses/{course_id} with {"course": {...}} for identity + blueprint flags
  2) PUT /api/v1/courses/{course_id}/settings with settings payload (if any)
  3) (optional) POST /api/v1/courses/{course_id}/blueprint_templates/default/migrations
     to queue a blueprint sync with copy_settings.

Notes:
- We use conservative allowlists for course fields. Unknown keys are ignored safely.
- Blueprint fields (if present): blueprint, blueprint_restrictions, 
  use_blueprint_restrictions_by_object_type, blueprint_restrictions_by_object_type.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, Optional, Protocol

import requests
from logging_setup import get_logger

__all__ = ["import_course_settings"]


class CanvasLike(Protocol):
    def put(self, endpoint: str, **kwargs) -> requests.Response: ...
    def post(self, endpoint: str, **kwargs) -> requests.Response: ...


# Conservative allowlist of course fields we apply via PUT /courses/{id}
_COURSE_ALLOW = {
    "name",
    "course_code",
    # Blueprint-related
    "blueprint",
    "blueprint_restrictions",
    "use_blueprint_restrictions_by_object_type",
    "blueprint_restrictions_by_object_type",
}


def _read_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _merge_settings(meta_settings: Optional[Dict[str, Any]], file_settings: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not meta_settings and not file_settings:
        return None
    merged = dict(meta_settings or {})
    merged.update(file_settings or {})
    return merged


def _filter_course_fields(meta: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract allowlisted fields from metadata and ensure dict-typed fields are dicts.
    """
    course_fields: Dict[str, Any] = {}
    for k in _COURSE_ALLOW:
        if k in meta and meta[k] is not None:
            v = meta[k]
            if k in {"blueprint_restrictions", "blueprint_restrictions_by_object_type"}:
                if isinstance(v, dict):
                    course_fields[k] = v
            else:
                course_fields[k] = v
    return course_fields


def import_course_settings(
    *,
    target_course_id: int,
    export_root: Path,
    canvas: CanvasLike,
    queue_blueprint_sync: bool = False,
    blueprint_sync_options: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Apply course identity/settings and optional blueprint sync.
    """
    logger = get_logger(course_id=target_course_id, artifact="course")

    course_dir = export_root / "course"
    meta_path = course_dir / "course_metadata.json"
    file_settings_path = course_dir / "settings.json"

    if not meta_path.exists() and not file_settings_path.exists():
        logger.warning("No course metadata/settings found under %s", course_dir)
        return

    meta: Dict[str, Any] = {}
    if meta_path.exists():
        try:
            meta = _read_json(meta_path)
        except Exception as e:
            logger.exception("Failed to read %s: %s", meta_path, e)

    # 1) Course identity + blueprint flags
    course_fields = _filter_course_fields(meta)
    if course_fields:
        payload = {"course": course_fields}
        logger.debug("Updating course fields: %s", payload)
        resp = canvas.put(f"/api/v1/courses/{target_course_id}", json=payload)
        resp.raise_for_status()
        logger.info("Updated course fields for course_id=%s", target_course_id)
    else:
        logger.debug("No allowlisted course fields found to update.")

    # 2) Course settings
    meta_settings = meta.get("settings") if isinstance(meta.get("settings"), dict) else None
    file_settings = None
    if file_settings_path.exists():
        try:
            file_settings = _read_json(file_settings_path)
        except Exception as e:
            logger.exception("Failed to read %s: %s", file_settings_path, e)

    settings = _merge_settings(meta_settings, file_settings)
    if settings:
        logger.debug("Updating course settings: %s", settings)
        resp2 = canvas.put(f"/api/v1/courses/{target_course_id}/settings", json=settings)
        resp2.raise_for_status()
        logger.info("Updated course settings for course_id=%s", target_course_id)

    # 3) Optional: queue a blueprint sync
    if queue_blueprint_sync:
        # If metadata does not say blueprint, we still try; Canvas will error if not a blueprint course.
        body = {"copy_settings": True}
        if isinstance(blueprint_sync_options, dict):
            body.update(blueprint_sync_options)
        logger.info("Queueing blueprint sync: %s", body)
        try:
            resp3 = canvas.post(f"/api/v1/courses/{target_course_id}/blueprint_templates/default/migrations", json=body)
            resp3.raise_for_status()
            logger.info("Queued blueprint sync for course_id=%s", target_course_id)
        except Exception as e:
            logger.exception("Failed to queue blueprint sync: %s", e)

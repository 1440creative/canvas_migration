from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from logging_setup import get_logger

# Safe module-level logger (no course id at import time)
log = get_logger(artifact="course_settings", course_id="-")


def _read_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _api_base(canvas) -> str:
    """
    Resolve base URL used by requests_mock in tests.
    DummyCanvas in tests exposes `api_base`; CanvasAPI exposes `base_url` or `api_base`.
    """
    base = getattr(canvas, "api_base", None) or getattr(canvas, "base_url", None)
    if not base:
        raise RuntimeError("Canvas client missing api_base/base_url")
    return base.rstrip("/")


def _full_url(base: str, endpoint: str) -> str:
    # Ensure we hit /api/v1/... even if caller passed "/v1/..."
    if not endpoint.startswith("/api/"):
        endpoint = endpoint if endpoint.startswith("/") else ("/" + endpoint)
        endpoint = "/api" + endpoint
    return f"{base}{endpoint}"


def _normalize_int_map(raw: Optional[Dict[Any, Any]]) -> Dict[int, int]:
    normalized: Dict[int, int] = {}
    for k, v in (raw or {}).items():
        try:
            old_id = int(k)
            new_id = int(v)
        except (TypeError, ValueError):
            continue
        normalized[old_id] = new_id
    return normalized


def import_course_settings(
    *,
    target_course_id: int,
    export_root: Path,
    canvas,
    id_map: Optional[Dict[str, Dict[Any, Any]]] = None,
    queue_blueprint_sync: bool = False,
    blueprint_sync_options: Optional[Dict[str, Any]] = None,
) -> Dict[str, int]:
    """
    Import course-level settings and related bits:

      1) PUT /api/v1/courses/:id with fields from course/course_metadata.json (selected keys)
         Also PUT /api/v1/courses/:id/settings if metadata.settings present.

      2) PUT syllabus HTML if course/syllabus.html exists.

      3) Set default_view and front page from course/home.json if present.

      4) Optionally queue Blueprint sync:
         POST /api/v1/courses/:id/blueprint_templates/default/migrations
         with blueprint_sync_options (if any).
    """
    # Per-invocation logger with the actual course id (so logs include it)
    lg = get_logger(artifact="course_settings", course_id=target_course_id)

    base = _api_base(canvas)
    counts = {"updated": 0}
    course_dir = export_root / "course"

    # --- 1) course metadata -> two endpoints
    meta_path = course_dir / "course_metadata.json"
    if meta_path.exists():
        meta = _read_json(meta_path)

        # Fields accepted by /courses/:id
        field_map = {
            "name": "name",
            "course_code": "course_code",
            "account_id": "account_id",
            "start_at": "start_at",
            "end_at": "end_at",
            "sis_course_id": "sis_course_id",
            "term_id": "enrollment_term_id",
            "is_blueprint": "is_blueprint_course",
            "default_view": "default_view",
            "time_zone": "time_zone",
            "locale": "locale",
            "is_public": "is_public",
            "public_syllabus": "public_syllabus",
        }

        course_fields: Dict[str, Any] = {}
        for src, dest in field_map.items():
            value = meta.get(src)
            if value is not None:
                course_fields[dest] = value

        for key in (
            "blueprint",
            "blueprint_restrictions",
            "use_blueprint_restrictions_by_object_type",
            "blueprint_restrictions_by_object_type",
        ):
            if meta.get(key) is not None:
                course_fields[key] = meta[key]

        # Rewrite course image using file id_map when available
        files_map = _normalize_int_map((id_map or {}).get("files"))
        image_id = meta.get("image_id") or meta.get("image_id_str")
        try:
            old_image_id = int(image_id) if image_id is not None else None
        except (TypeError, ValueError):
            old_image_id = None

        if old_image_id is not None:
            new_image_id = files_map.get(old_image_id)
            if new_image_id is not None:
                course_fields["image_id"] = new_image_id
                # Clear stale URL so Canvas rebuilds from new image
                course_fields["image_url"] = None
            else:
                lg.warning(
                    "Course image %s not found in files id_map; leaving image unchanged",
                    old_image_id,
                )

        # PUT /courses/:id (hit the mocked URL)
        if course_fields:
            url = _full_url(base, f"/v1/courses/{target_course_id}")
            lg.debug("PUT /courses/%s from course_metadata.json", target_course_id)
            # Canvas expects course-level updates wrapped in {"course": {...}}
            requests.put(url, json={"course": course_fields})
            counts["updated"] += 1

        # PUT /courses/:id/settings if present
        settings = meta.get("settings")
        if isinstance(settings, dict) and settings:
            url = _full_url(base, f"/v1/courses/{target_course_id}/settings")
            lg.debug("PUT /courses/%s/settings", target_course_id)
            requests.put(url, json=settings)
            counts["updated"] += 1

    # --- 2) syllabus HTML
    syllabus_html = course_dir / "syllabus.html"
    if syllabus_html.exists():
        try:
            html = syllabus_html.read_text(encoding="utf-8")
            url = _full_url(base, f"/v1/courses/{target_course_id}")
            lg.debug("PUT syllabus_body via /courses/%s", target_course_id)
            requests.put(url, json={"course": {"syllabus_body": html}})
            lg.info("Syllabus HTML updated")
            counts["updated"] += 1
        except Exception as e:
            lg.warning("Failed to update syllabus HTML: %s", e)

    # --- 3) home page/front page
    home_json = course_dir / "home.json"
    if home_json.exists():
        try:
            hmeta = _read_json(home_json)
            default_view = hmeta.get("default_view")
            front_url = hmeta.get("front_page_url")

            if default_view:
                url = _full_url(base, f"/v1/courses/{target_course_id}")
                lg.debug("PUT course default_view=%s", default_view)
                try:
                    requests.put(url, json={"course": {"default_view": default_view}})
                    counts["updated"] += 1
                except Exception as e:
                    lg.warning("Failed to set default_view=%s: %s", default_view, e)

            if front_url:
                url = _full_url(base, f"/v1/courses/{target_course_id}/pages/{front_url}")
                lg.debug("PUT wiki_page front_page=true url=%s", front_url)
                try:
                    requests.put(url, json={"wiki_page": {"front_page": True}})
                    lg.info("Set front page: %s", front_url)
                    counts["updated"] += 1
                except Exception as e:
                    lg.warning("Failed to set front page %s: %s", front_url, e)
        except Exception as e:
            lg.warning("Failed to import home.json: %s", e)

    # --- 4) optional: queue blueprint sync
    if queue_blueprint_sync:
        try:
            url = _full_url(base, f"/v1/courses/{target_course_id}/blueprint_templates/default/migrations")
            payload = blueprint_sync_options or {}
            # Default to copying settings; allow caller to override/extend.
            payload = {"copy_settings": True}
            if blueprint_sync_options:
                payload.update(blueprint_sync_options)
            lg.debug(
                "POST /api/v1/courses/%s/blueprint_templates/default/migrations payload=%s",
                target_course_id, payload
            )
            requests.post(url, json=payload)
        except Exception as e:
            lg.warning("Could not queue Blueprint sync: %s", e)

    lg.info("Course settings import complete")
    return counts

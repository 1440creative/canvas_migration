from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from logging_setup import get_logger

log = get_logger(artifact="course_settings")


def _read_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _choose_blueprint_template_fragment(meta: Dict[str, Any]) -> str:
    """
    Return a template fragment usable in the endpoint:
      /courses/:id/blueprint_templates/{frag}/migrations

    Prefers a concrete numeric id if present, otherwise falls back to "default".
    """
    # export/export_blueprint_settings writes {"template":{"id":...}, ...}
    t = (meta or {}).get("template") or {}
    tid = t.get("id")
    if isinstance(tid, int):
        return str(tid)
    return "default"


def import_course_settings(
    *,
    target_course_id: int,
    export_root: Path,
    canvas,
    queue_blueprint_sync: bool = False,   # <— NEW: accepted & honored
) -> Dict[str, int]:
    """
    Import minimal course-level settings:
      - PUT /courses/:id with fields from course/course_settings.json (if present)
      - PUT syllabus_body if syllabus.html exists
      - Set default_view/wiki front page if home.json present
      - Optionally queue a Blueprint sync if --queue-blueprint-sync was requested and
        blueprint metadata exists in export.
    """
    counts = {"updated": 0}
    course_dir = export_root / "course"

    # 1) settings.json (optional)
    settings_path = course_dir / "course_settings.json"
    if settings_path.exists():
        try:
            body = _read_json(settings_path)
            log.debug("PUT course fields")
            canvas.put(f"/api/v1/courses/{target_course_id}", json=body)
            counts["updated"] += 1
        except Exception as e:
            log.error("Failed to update course fields: %s", e)

    # 2) syllabus (optional)
    syllabus_html = course_dir / "syllabus.html"
    if syllabus_html.exists():
        try:
            html = syllabus_html.read_text(encoding="utf-8")
            log.debug("PUT syllabus_body")
            canvas.put(
                f"/api/v1/courses/{target_course_id}",
                json={"course": {"syllabus_body": html}},
            )
            log.info("Syllabus HTML updated")
        except Exception as e:
            log.warning("Failed to update syllabus HTML: %s", e)

    # 3) home page (optional)
    home_json = course_dir / "home.json"
    if home_json.exists():
        try:
            meta = _read_json(home_json)
            default_view = meta.get("default_view")
            front_url = meta.get("front_page_url")
            if default_view:
                log.debug("PUT course default_view=%s", default_view)
                try:
                    canvas.put(
                        f"/api/v1/courses/{target_course_id}",
                        json={"course": {"default_view": default_view}},
                    )
                except Exception as e:
                    log.warning("Failed to set default_view=%s: %s", default_view, e)
            if front_url:
                log.debug("PUT wiki_page front_page=true url=%s", front_url)
                try:
                    canvas.put(
                        f"/api/v1/courses/{target_course_id}/pages/{front_url}",
                        json={"wiki_page": {"front_page": True}},
                    )
                    log.info("Set front page: %s", front_url)
                except Exception as e:
                    log.warning("Failed to set front page %s: %s", front_url, e)
        except Exception as e:
            log.warning("Failed to import home.json: %s", e)

    # 4) Optional: queue blueprint sync if requested & metadata present
    if queue_blueprint_sync:
        bp_dir = export_root / "blueprint"
        meta_path = bp_dir / "blueprint_metadata.json"
        if meta_path.exists():
            try:
                bp_meta = _read_json(meta_path)
                frag = _choose_blueprint_template_fragment(bp_meta)  # id or "default"
                endpoint = f"/api/v1/courses/{target_course_id}/blueprint_templates/{frag}/migrations"
                log.debug("POST blueprint sync", extra={"endpoint": endpoint})
                canvas.post(endpoint, json={})
            except Exception as e:
                log.warning("Could not queue Blueprint sync: %s", e)

    log.info("Course settings import complete")
    return counts

# export/export_settings.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from logging_setup import get_logger
from utils.api import CanvasAPI
from utils.fs import ensure_dir, atomic_write, json_dumps_stable
from .export_syllabus import export_syllabus as export_course_syllabus

def export_course_settings(course_id: int, export_root: Path, api: CanvasAPI) -> Dict[str, Any]:
    """
    Export high-level course info + the settings blob.
    - Writes:
        export/data/{course_id}/course/course_metadata.json
        export/data/{course_id}/course/course_settings.json
    - Returns a small dict summary (includes blueprint flag).
    """
    log = get_logger(artifact="course_settings", course_id=course_id)

    course_root = export_root / str(course_id)
    out_dir = course_root / "course"
    ensure_dir(out_dir)

    # Basic course info (metadata)
    course = api.get(f"courses/{course_id}")
    if not isinstance(course, dict):
        raise TypeError("Expected course dict from Canvas API")

    metadata = {
        "id": course.get("id"),
        "uuid": course.get("uuid"),
        "sis_course_id": course.get("sis_course_id"),
        "name": course.get("name"),
        "course_code": course.get("course_code"),
        "term_id": (course.get("enrollment_term_id") or course.get("term", {}).get("id")),
        "account_id": course.get("account_id"),
        "workflow_state": course.get("workflow_state"),
        "start_at": course.get("start_at"),
        "end_at": course.get("end_at"),
        "apply_assignment_group_weights": course.get("apply_assignment_group_weights"),
        "is_blueprint": bool(course.get("blueprint") or course.get("is_blueprint")),
        "default_view": course.get("default_view"),
        "time_zone": course.get("time_zone"),
        "locale": course.get("locale"),
        "is_public": course.get("is_public"),
        "public_syllabus": course.get("public_syllabus"),
        "image_id": course.get("image_id"),
        "image_url": course.get("image_url"),
        "blueprint": course.get("blueprint"),
        "blueprint_restrictions": course.get("blueprint_restrictions"),
        "use_blueprint_restrictions_by_object_type": course.get("use_blueprint_restrictions_by_object_type"),
        "blueprint_restrictions_by_object_type": course.get("blueprint_restrictions_by_object_type"),
        "default_wiki_page_title": course.get("default_wiki_page_title"),
        "source_api_url": api.api_root.rstrip("/") + f"/courses/{course_id}",
    }

    image_id = metadata.get("image_id")
    if image_id:
        try:
            file_detail = api.get(f"files/{image_id}")
            if isinstance(file_detail, dict):
                metadata["course_image_filename"] = file_detail.get("filename")
                metadata["course_image_display_name"] = file_detail.get("display_name")
        except Exception:
            # optional info only; ignore errors
            pass
    # Course settings blob
    settings = api.get(f"courses/{course_id}/settings")
    if not isinstance(settings, dict):
        raise TypeError("Expected settings dict from Canvas API")

    metadata["settings"] = settings
    atomic_write(out_dir / "course_metadata.json", json_dumps_stable(metadata))
    atomic_write(out_dir / "course_settings.json", json_dumps_stable(settings))

    # Course navigation ordering + visibility
    try:
        tabs = api.get(f"courses/{course_id}/tabs")
    except Exception as exc:
        log.warning("Failed to export course navigation tabs: %s", exc)
        tabs = []

    navigation: list[dict[str, Any]] = []
    if isinstance(tabs, list):
        for tab in tabs:
            if not isinstance(tab, dict):
                continue
            tab_id = tab.get("id")
            if not tab_id:
                continue
            navigation.append(
                {
                    "id": tab_id,
                    "label": tab.get("label"),
                    "hidden": bool(tab.get("hidden")),
                    "position": tab.get("position"),
                    "visibility": tab.get("visibility"),
                    "type": tab.get("type"),
                    "html_url": tab.get("html_url"),
                    "has_permission": tab.get("has_permission"),
                    "can_add_to_nav": tab.get("can_add_to_nav"),
                    "course_navigation": tab.get("course_navigation"),
                }
            )

    if navigation:
        navigation_sorted = sorted(
            navigation,
            key=lambda item: (
                1 if item.get("position") in (None, "") else 0,
                item.get("position") or 0,
                str(item.get("id")),
            ),
        )
        atomic_write(out_dir / "course_navigation.json", json_dumps_stable(navigation_sorted))
        log.debug("exported %s course navigation tabs", len(navigation_sorted))
    
    #syllabus html
    try:
        export_course_syllabus(course_id, export_root, api)
    except Exception as e:
        log = get_logger(artifact="syllabus_export", course_id=course_id)
        log.warning("Failed to export syllabus: %s", e)


    log.info("exported course info + settings", extra={"is_blueprint": metadata["is_blueprint"]})
    return {"is_blueprint": metadata["is_blueprint"]}

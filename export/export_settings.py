# export/export_settings.py
from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any, Dict, Optional, List
from urllib.parse import urlparse

from logging_setup import get_logger
from utils.api import CanvasAPI, DEFAULT_TIMEOUT
from utils.fs import ensure_dir, atomic_write, json_dumps_stable
from .export_syllabus import export_syllabus as export_course_syllabus

_IMAGE_CHUNK = 1024 * 512  # 512 KiB


def _sanitize_scheme_entries(raw: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    scheme: List[Dict[str, Any]] = []
    if not isinstance(raw, list):
        return scheme
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        value = entry.get("value")
        if not isinstance(name, str):
            continue
        try:
            value_f = float(value)
        except (TypeError, ValueError):
            continue
        scheme.append({"name": name, "value": value_f})
    return scheme


def _fetch_grading_standard(
    *,
    api: CanvasAPI,
    course_id: int,
    account_id: Optional[int],
    standard_id: Any,
    log,
) -> Optional[Dict[str, Any]]:
    """Fetch grading standard definition from Canvas."""

    if standard_id is None:
        return None

    sid = str(standard_id)
    contexts: List[tuple[str, str]] = [
        ("course", f"courses/{course_id}/grading_standards"),
    ]
    if account_id is not None:
        contexts.append(("account", f"accounts/{account_id}/grading_standards"))
    contexts.append(("unscoped", f"grading_standards/{sid}"))

    for context_type, endpoint in contexts:
        try:
            data = api.get(endpoint)
        except Exception:
            continue

        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                if str(item.get("id")) != sid:
                    continue
                scheme = _sanitize_scheme_entries(item.get("grading_scheme"))
                if not scheme:
                    continue
                return {
                    "id": item.get("id"),
                    "title": item.get("title") or item.get("name"),
                    "context_type": item.get("context_type") or context_type.title(),
                    "context_id": item.get("context_id"),
                    "grading_scheme": scheme,
                }

        elif isinstance(data, dict):
            if str(data.get("id")) != sid and context_type != "unscoped":
                continue
            scheme = _sanitize_scheme_entries(data.get("grading_scheme"))
            if not scheme:
                continue
            return {
                "id": data.get("id"),
                "title": data.get("title") or data.get("name"),
                "context_type": data.get("context_type") or context_type.title(),
                "context_id": data.get("context_id"),
                "grading_scheme": scheme,
            }

    log.warning("Unable to fetch grading standard %s", standard_id)
    return None


def _safe_name(candidate: str) -> str:
    """Return basename without directory components."""
    name = Path(candidate or "").name
    return name or "course_image"


def _download_course_image(
    *,
    api: CanvasAPI,
    image_url: str,
    metadata: Dict[str, Any],
    dest_dir: Path,
    log,
) -> Optional[str]:
    """
    Download the course card image so we can re-upload during import.
    Returns relative filename if successful.
    """
    try:
        response = api.session.get(image_url, stream=True, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
    except Exception as exc:
        log.warning("Failed to download course image: %s", exc)
        return None

    preferred = metadata.get("course_image_filename") or metadata.get("course_image_display_name")
    parsed_path = urlparse(image_url).path
    from_url = Path(parsed_path).name
    candidate = _safe_name(preferred or from_url or "course_image")

    # Ensure we have an extension (prefer metadata, then URL path, then content-type)
    suffix = Path(candidate).suffix
    if not suffix:
        url_suffix = Path(from_url).suffix
        content_type = response.headers.get("Content-Type") or response.headers.get("content-type")
        guessed = None
        if content_type:
            guessed = mimetypes.guess_extension(content_type.split(";")[0].strip()) or None
        ext = url_suffix or guessed or ".jpg"
        if not ext.startswith("."):
            ext = f".{ext}"
        candidate = f"{candidate}{ext}"

    dest_path = dest_dir / candidate
    try:
        with response as resp:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            with dest_path.open("wb") as fh:
                for chunk in resp.iter_content(_IMAGE_CHUNK):
                    if chunk:
                        fh.write(chunk)
    except Exception as exc:
        log.warning("Failed to save course image %s: %s", dest_path, exc)
        return None

    log.debug("Exported course image to %s", dest_path)
    return dest_path.name

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
        "grading_standard_id": course.get("grading_standard_id"),
        "restrict_enrollments_to_course_dates": course.get("restrict_enrollments_to_course_dates"),
        "restrict_student_future_view": course.get("restrict_student_future_view"),
        "restrict_student_past_view": course.get("restrict_student_past_view"),
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

    if isinstance(settings, dict):
        if "grading_standard_enabled" in settings:
            metadata["grading_standard_enabled"] = bool(settings.get("grading_standard_enabled"))
        if settings.get("grading_standard_id") and not metadata.get("grading_standard_id"):
            metadata["grading_standard_id"] = settings.get("grading_standard_id")

    grading_standard_info = None
    if metadata.get("grading_standard_enabled") and metadata.get("grading_standard_id"):
        grading_standard_info = _fetch_grading_standard(
            api=api,
            course_id=course_id,
            account_id=metadata.get("account_id"),
            standard_id=metadata.get("grading_standard_id"),
            log=log,
        )
        if grading_standard_info:
            metadata["grading_standard"] = grading_standard_info

    image_url = metadata.get("image_url")
    if image_url:
        rel_image = _download_course_image(api=api, image_url=image_url, metadata=metadata, dest_dir=out_dir, log=log)
        if rel_image:
            metadata["course_image_export_path"] = rel_image

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

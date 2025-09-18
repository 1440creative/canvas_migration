# export/export_syllabus.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from logging_setup import get_logger

def export_syllabus(course_id: int, export_root: Path, api) -> Path:
    """
    Fetch the syllabus HTML and write:
      <export_root>/<course_id>/course/syllabus.html   (if present)
      <export_root>/<course_id>/course/syllabus.json   (metadata/flags)
    Returns the course directory path.
    """
    log = get_logger(artifact="syllabus_export", course_id=course_id)

    # Defensive: ensure export_root is a Path
    if export_root is None:
        raise ValueError("export_syllabus: export_root is None")
    if not isinstance(export_root, Path):
        export_root = Path(export_root)

    out_dir = export_root / str(course_id) / "course"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Ask Canvas to include the syllabus body
    try:
        course: Dict[str, Any] = api.get(
            f"/api/v1/courses/{course_id}",
            params={"include[]": "syllabus_body"},
        )
    except Exception as e:
        log.warning("Failed to fetch course for syllabus: %s", e)
        course = {}

    body = (course or {}).get("syllabus_body")

    meta_path = out_dir / "syllabus.json"
    if not body:
        meta = {"has_syllabus": False}
        meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        log.info("No syllabus_body present; wrote %s", meta_path)
        return out_dir

    html_path = out_dir / "syllabus.html"
    html = body if ("<html" in body.lower()) else "<!doctype html><meta charset='utf-8'>\n" + body
    html_path.write_text(html, encoding="utf-8")

    meta = {"has_syllabus": True, "format": "html", "filename": "syllabus.html", "length": len(body)}
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    log.info("Exported syllabus to %s", html_path)
    return out_dir

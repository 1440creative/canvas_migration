# export/export_syllabus.py
from __future__ import annotations
from pathlib import Path
from typing import Optional, Dict, Any
from logging_setup import get_logger

def export_syllabus(course_id: int, export_root: Path, api) -> Optional[Path]:
    """
    Writes the course syllabus HTML (if present) to:
      <export_root>/<course_id>/course/syllabus.html
    Returns the path written, or None if no syllabus.
    """
    log = get_logger(artifact="syllabus_export", course_id=course_id)

    # Always build the path explicitly and return it
    course_dir = Path(export_root) / str(course_id) / "course"
    course_dir.mkdir(parents=True, exist_ok=True)
    out_path = course_dir / "syllabus.html"

    try:
        # Ask Canvas to include the syllabus body
        course: Dict[str, Any] = api.get(
            f"/api/v1/courses/{course_id}",
            params={"include[]": "syllabus_body"},
        )

        html = (course or {}).get("syllabus_body") or ""
        if not html.strip():
            log.info("No syllabus content on source course; nothing to write.")
            return None

        out_path.write_text(html, encoding="utf-8")
        log.info("Wrote syllabus to %s", out_path)
        return out_path

    except Exception as e:
        # Log the exception clearly so it’s easy to grep later
        log.exception("Failed to export syllabus: %s", e)
        return None

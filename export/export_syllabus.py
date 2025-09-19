# export/export_syllabus.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from logging_setup import get_logger


class CanvasLike(Protocol):
    """Minimal API surface we rely on from utils.api.CanvasAPI."""
    def get(self, endpoint: str, params: dict | None = None) -> dict | list: ...


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def export_syllabus(course_id: int, export_root: Path, api: CanvasLike) -> None:
    """
    Export the course syllabus HTML to:

        {export_root}/{course_id}/course/syllabus.html

    - Creates directories as needed.
    - Writes an empty file if no syllabus is set (keeps import idempotent).
    - Logs warnings instead of raising to avoid breaking the overall export.
    """
    log = get_logger(artifact="syllabus_export", course_id=course_id)

    # Normalize export_root to a Path (defensive against callers passing str/None)
    export_root = Path(str(export_root))
    out_html = export_root / str(course_id) / "course" / "syllabus.html"

    try:
        # Ask Canvas to include the syllabus body. Many tenants return it by default,
        # but include[]=syllabus_body is harmless and future-proof.
        course_resp = api.get(
            f"/api/v1/courses/{course_id}",
            params={"include[]": "syllabus_body"},
        )

        # Some API wrappers might return a list on error; guard for that.
        course: dict[str, Any] = course_resp if isinstance(course_resp, dict) else {}

        body = course.get("syllabus_body") or ""
        if isinstance(body, str) and body.strip():
            _write_text(out_html, body)
            log.info("Wrote %s", out_html.as_posix())
        else:
            _write_text(out_html, "")
            log.info("No syllabus HTML found; wrote empty %s", out_html.as_posix())

    except Exception as e:
        # Don't fail the whole export; warn and ensure directory exists
        log.warning("Failed to export syllabus: %s", e)
        out_html.parent.mkdir(parents=True, exist_ok=True)
        # Optionally, leave no file on error to make issues obvious in the tree.
        # rather always create a file?, uncomment:
        # _write_text(out_html, "")

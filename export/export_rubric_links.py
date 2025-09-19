# export/export_rubric_links.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from logging_setup import get_logger

__all__ = ["export_rubric_links"]

class CanvasLike:
    def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None):
        ...

def _course_dir(export_root: Path, course_id: int) -> Path:
    export_root = Path(export_root)
    if export_root.name == str(course_id):
        return export_root / "course"
    return export_root / str(course_id) / "course"

def _get_all(api: CanvasLike, endpoint: str, params: Optional[Dict[str, Any]] = None):
    return api.get(endpoint, params=params)

def export_rubric_links(course_id: int, export_root: Path, api: CanvasLike) -> List[Dict[str, Any]]:
    """
    Export rubric→assignment links for a course.

    Tries GET /rubric_associations; if not available, falls back to
    scanning assignments with include[]=rubric,rubric_settings.

    Writes: <export_root>/<course_id>/course/rubric_links.json
    """
    log = get_logger(artifact="rubric_links_export", course_id=course_id)
    out_dir = _course_dir(export_root, course_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "rubric_links.json"

    # Build rubric id -> title map to enrich the export
    try:
        rubrics = _get_all(api, f"/api/v1/courses/{course_id}/rubrics")
    except Exception:
        rubrics = []
    rubric_titles: Dict[int, str] = {}
    if isinstance(rubrics, list):
        for r in rubrics:
            rid = r.get("id")
            title = r.get("title") or r.get("title_text") or r.get("rubric_title")
            if isinstance(rid, int) and title:
                rubric_titles[rid] = title

    links: List[Dict[str, Any]] = []

    # Preferred: direct rubric_associations
    direct: List[Dict[str, Any]] = []
    try:
        ra = _get_all(api, f"/api/v1/courses/{course_id}/rubric_associations")
        if isinstance(ra, list):
            direct = ra
    except Exception as e:
        log.debug("rubric_associations not accessible: %s", e)

    if direct:
        for assoc in direct:
            rid = assoc.get("rubric_id")
            otype = assoc.get("association_type") or assoc.get("context_type") or "Assignment"
            oid = assoc.get("association_id") or assoc.get("context_id")
            if not (isinstance(rid, int) and isinstance(oid, int)):
                continue
            links.append({
                "rubric_id": rid,
                "rubric_title": rubric_titles.get(rid),
                "object_type": otype,
                "object_id": oid,
                "assignment_title": None,
                "use_for_grading": bool(assoc.get("use_for_grading", True)),
                "hide_score_total": bool(assoc.get("hide_score_total", False)),
                "purpose": (assoc.get("purpose") or "grading"),
            })
    else:
        # Fallback: scan assignments for rubric_settings
        try:
            assignments = _get_all(
                api,
                f"/api/v1/courses/{course_id}/assignments",
                params={"include[]": ["rubric", "rubric_settings"]},
            )
        except Exception:
            assignments = []

        for a in assignments or []:
            aid = a.get("id")
            if not isinstance(aid, int):
                continue
            rs = a.get("rubric_settings") or {}
            rid = rs.get("id") or rs.get("rubric_id")
            if not isinstance(rid, int):
                continue
            links.append({
                "rubric_id": rid,
                "rubric_title": rubric_titles.get(rid),
                "object_type": "Assignment",
                "object_id": aid,
                "assignment_title": a.get("name"),
                "use_for_grading": bool(rs.get("use_for_grading", True)),
                "hide_score_total": bool(rs.get("hide_score_total", False)),
                "purpose": (rs.get("purpose") or "grading"),
            })

    out_path.write_text(__import__("json").dumps(links, indent=2) + "\n", encoding="utf-8")
    log.info("Wrote rubric links")
    return links

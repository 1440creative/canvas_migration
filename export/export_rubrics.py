# export_rubrics.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from logging_setup import get_logger

__all__ = ["export_rubrics"]

class CanvasLike:
    def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None):
        ...

def _course_dir(export_root: Path, course_id: int) -> Path:
    export_root = Path(export_root)
    return export_root / "course" / "rubrics"

def _slim_rubric(r: Dict[str, Any]) -> Dict[str, Any]:
    """Reduce Canvas rubric to the minimal structure our importer/tests need."""
    out: Dict[str, Any] = {
        "id": r.get("id"),
        "title": r.get("title"),
        "points_possible": r.get("points_possible"),  # <-- required by test
        "free_form_criterion_comments": bool(r.get("free_form_criterion_comments", False)),
        "criteria": [],
        "associations": [],
    }

    # criteria
    for c in (r.get("criteria") or []):
        out["criteria"].append({
            "description": c.get("description"),
            "long_description": c.get("long_description"),
            "points": c.get("points"),
            "ignore_for_scoring": bool(c.get("ignore_for_scoring", False)),
            "ratings": [
                {"description": rt.get("description"), "points": rt.get("points")}
                for rt in (c.get("ratings") or [])
            ],
        })

    # associations (only the assignment mapping details we need later)
    for a in (r.get("associations") or []):
        out["associations"].append({
            "association_type": a.get("association_type"),
            "association_id": a.get("association_id"),
            "use_for_grading": bool(a.get("use_for_grading", True)),
            "purpose": a.get("purpose") or "grading",
            "hide_score_total": bool(a.get("hide_score_total", False)),
            "hide_points": bool(a.get("hide_points", False)),
        })

    return out

def export_rubrics(course_id: int, export_root: Path, canvas: CanvasLike) -> List[Dict[str, Any]]:
    """
    Export rubrics with associations (slim form) and write:
      - per-rubric JSON under course/<id>/rubrics/<rubric_id>.json
      - course/<id>/rubrics/index.json (metadata index if you already rely on it)
      - rubrics/rubrics.json (consolidated slim list used by tests/importer)
    """
    log = get_logger(artifact="rubrics_export", course_id=course_id)

    # Fetch rubrics with associations
    rubrics = canvas.get(f"/api/v1/courses/{course_id}/rubrics")
    if not isinstance(rubrics, list):
        rubrics = []

    # Slim them down
    slim: List[Dict[str, Any]] = [_slim_rubric(r) for r in rubrics]

    # Preserve existing per-rubric layout (under course/<id>/rubrics)
    course_dir = _course_dir(export_root, course_id)
    course_dir.mkdir(parents=True, exist_ok=True)
    for r in slim:
        rid = r.get("id")
        if rid is not None:
            (course_dir / f"rubric_{rid}.json").write_text(json.dumps(r, indent=2) + "\n", encoding="utf-8")
    # optional index (kept for compatibility)
    (course_dir / "index.json").write_text(
        json.dumps([{"id": r.get("id"), "title": r.get("title")} for r in slim], indent=2) + "\n",
        encoding="utf-8"
    )

    # Consolidated slim list where tests look
    top_rubrics_dir = Path(export_root) / "rubrics"
    top_rubrics_dir.mkdir(parents=True, exist_ok=True)
    (top_rubrics_dir / "rubrics.json").write_text(json.dumps(slim, indent=2) + "\n", encoding="utf-8")

    log.info("Exported %d rubrics", len(slim))
    return slim

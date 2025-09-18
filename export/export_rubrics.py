# export/export_rubrics.py
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Protocol
import json
from logging_setup import get_logger

class CanvasLike(Protocol):
    def get(self, endpoint: str, params: dict | None = None) -> Any: ...
    @property
    def api_root(self) -> str: ...

def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def _slim_rubric(r: dict) -> dict:
    # Keep only fields we’ll need to recreate
    out = {
        "id": r.get("id"),
        "title": r.get("title"),
        "free_form_criterion_comments": r.get("free_form_criterion_comments", False),
        "criteria": [],
        "associations": [],
        "points_possible": r.get("points_possible"),
    }
    for c in (r.get("criteria") or []):
        out["criteria"].append({
            "id": c.get("id"),
            "description": c.get("description"),
            "long_description": c.get("long_description"),
            "ignore_for_scoring": c.get("ignore_for_scoring", False),
            "points": c.get("points"),
            "ratings": [
                {
                    "id": rt.get("id"),
                    "description": rt.get("description"),
                    "long_description": rt.get("long_description"),
                    "points": rt.get("points"),
                } for rt in (c.get("ratings") or [])
            ],
        })

    # The rubrics API can include rubric associations when include[]=associations
    for a in (r.get("associations") or []):
        out["associations"].append({
            "association_type": a.get("association_type"),  # "Assignment" etc
            "association_id": a.get("association_id"),
            "use_for_grading": a.get("use_for_grading", True),
            "purpose": a.get("purpose", "grading"),
            "hide_score_total": a.get("hide_score_total", False),
            "hide_points": a.get("hide_points", False),
        })
    return out

def export_rubrics(course_id: int, export_root: Path, api: CanvasLike) -> List[dict]:
    log = get_logger(artifact="rubrics_export", course_id=course_id)
    rubrics_dir = export_root / "rubrics"
    _ensure_dir(rubrics_dir)

    params = {"include[]": ["full", "associations"]}
    rubrics = api.get(f"/api/v1/courses/{course_id}/rubrics", params=params)
    if not isinstance(rubrics, list):
        rubrics = []

    slims = [_slim_rubric(r) for r in rubrics]
    out_path = rubrics_dir / "rubrics.json"
    out_path.write_text(json.dumps(slims, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    log.info("Exported rubrics", extra={"count": len(slims), "path": str(out_path)})
    return slims

# importers/import_rubrics.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from logging_setup import get_logger

def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

def _find_rubrics_json(export_root: Path) -> Optional[Path]:
    """
    Prefer top-level rubrics/rubrics.json (new),
    fallback to legacy course/rubrics/rubrics.json.
    """
    p1 = Path(export_root) / "rubrics" / "rubrics.json"
    if p1.exists():
        return p1
    p2 = Path(export_root) / "course" / "rubrics" / "rubrics.json"
    if p2.exists():
        return p2
    return None

def import_rubrics(
    *,
    target_course_id: int,
    export_root: Path,
    canvas,
    id_map: Dict[str, Dict[Any, Any]] | None = None,
) -> Dict[str, int]:
    """
    Import rubrics and create rubric associations to mapped objects (assignments).
    Returns counters: {"imported","skipped","failed","total"}.
    """
    log = get_logger(artifact="rubrics_import", course_id=target_course_id)
    id_map = id_map or {}
    id_map.setdefault("rubrics", {})
    id_map.setdefault("assignments", {})

    src_path = _find_rubrics_json(export_root)
    if not src_path:
        log.info("No rubrics to import (missing %s)", (Path(export_root) / "rubrics" / "rubrics.json"))
        return {"imported": 0, "skipped": 0, "failed": 0, "total": 0}

    data = _read_json(src_path) or []
    if not isinstance(data, list):
        data = []

    imported = 0
    failed = 0
    skipped = 0

    for r in data:
        title = r.get("title") or "Untitled Rubric"
        criteria = r.get("criteria") or []
        # Build Canvas payload
        payload = {
            "rubric": {
                "title": title,
                "criteria": criteria,
            }
        }

        try:
            resp = canvas.post(f"/api/v1/courses/{target_course_id}/rubrics", json=payload)
            new = resp.json() if hasattr(resp, "json") else {}
            new_id = new.get("id")
            if not new_id:
                # Try alternate shapes defensively
                if isinstance(new, dict):
                    new_id = new.get("rubric_id") or new.get("data", {}).get("id")

            if not new_id:
                failed += 1
                log.error("failed to create rubric (no id) title=%r", title)
                continue

            # map old rubric id if present
            old_id = r.get("id")
            if isinstance(old_id, int):
                id_map["rubrics"][old_id] = new_id

            imported += 1

            # Create associations (e.g., to assignments) with mapped IDs
            for a in (r.get("associations") or []):
                if a.get("association_type") != "Assignment":
                    continue
                old_assignment_id = a.get("association_id")
                new_assignment_id = id_map.get("assignments", {}).get(old_assignment_id)
                if not new_assignment_id:
                    # cannot associate; skip silently
                    continue

                assoc_payload = {
                    "rubric_association": {
                        "rubric_id": new_id,
                        "association_type": "Assignment",
                        "association_id": new_assignment_id,
                        "use_for_grading": bool(a.get("use_for_grading", True)),
                        "hide_score_total": bool(a.get("hide_score_total", False)),
                        "purpose": a.get("purpose") or "grading",
                    }
                }
                try:
                    canvas.post(f"/api/v1/courses/{target_course_id}/rubric_associations", json=assoc_payload)
                except Exception as e:
                    # association failures shouldn't fail rubric creation
                    log.warning("rubric association failed title=%r error=%s", title, e)

        except Exception as e:
            failed += 1
            log.error("failed to create rubric title=%r error=%s", title, e)

    counters = {"imported": imported, "skipped": skipped, "failed": failed, "total": len(data)}
    log.info("Rubrics import complete. imported=%d skipped=%d failed=%d total=%d",
             counters["imported"], counters["skipped"], counters["failed"], counters["total"])
    return counters

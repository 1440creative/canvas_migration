# importers/import_rubrics.py
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Protocol, Optional
import json
from logging_setup import get_logger

class CanvasLike(Protocol):
    def get(self, endpoint: str, params: dict | None = None) -> Any: ...
    def post(self, endpoint: str, *, json: dict | None = None, data: dict | None = None) -> Any: ...
    @property
    def api_root(self) -> str: ...

def _read_json(p: Path) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None

def _make_rubric_payload(r: dict) -> dict:
    # Canvas accepts a JSON body with a "rubric" object on many tenants.
    # If your tenant insists on form-encoding, we can add a fallback later.
    rubric = {
        "title": r.get("title") or "Imported Rubric",
        "free_form_criterion_comments": bool(r.get("free_form_criterion_comments", False)),
        "criteria": [],
    }
    for c in (r.get("criteria") or []):
        rubric["criteria"].append({
            "description": c.get("description"),
            "long_description": c.get("long_description"),
            "ignore_for_scoring": bool(c.get("ignore_for_scoring", False)),
            "points": c.get("points"),
            "ratings": [
                {
                    "description": rt.get("description"),
                    "long_description": rt.get("long_description"),
                    "points": rt.get("points"),
                } for rt in (c.get("ratings") or [])
            ],
        })
    return {"rubric": rubric, "skip_updating_points": True}

def import_rubrics(
    *,
    target_course_id: int,
    export_root: Path,
    canvas: CanvasLike,
    id_map: Dict[str, Dict[Any, Any]],
) -> None:
    """
    Create course-level copies of rubrics and re-associate them to target assignments.
    Requires that assignments have already been imported (so id_map['assignments'] exists).
    """
    log = get_logger(artifact="rubrics", course_id=target_course_id)

    src_path = export_root / "rubrics" / "rubrics.json"
    rubrics = _read_json(src_path) or []
    if not rubrics:
        log.info("No rubrics.json found or empty; nothing to import")
        return

    rub_map: Dict[int, int] = id_map.setdefault("rubrics", {})
    asn_map: Dict[Any, Any] = (id_map.get("assignments") or {})

    created = 0
    associated = 0
    failed = 0

    for r in rubrics:
        old_rid = r.get("id")
        payload = _make_rubric_payload(r)
        try:
            resp = canvas.post(f"/api/v1/courses/{target_course_id}/rubrics", json=payload)
            body = getattr(resp, "json", lambda: {})()
        except Exception as e:
            failed += 1
            log.exception("Failed to create rubric %r: %s", r.get("title"), e)
            continue

        new_rid = (body or {}).get("id")
        if not isinstance(new_rid, int):
            failed += 1
            log.error("Rubric create returned no id for %r; body=%s", r.get("title"), body)
            continue

        created += 1
        if isinstance(old_rid, int):
            rub_map[old_rid] = new_rid
        log.info("Created rubric", extra={"old_id": old_rid, "new_id": new_rid, "title": r.get("title")})

        # Recreate associations (Assignment only)
        for a in (r.get("associations") or []):
            if a.get("association_type") != "Assignment":
                continue
            old_asn = a.get("association_id")
            new_asn = asn_map.get(old_asn)
            if not new_asn:
                log.debug("Skip association; assignment %s not mapped", old_asn)
                continue

            assoc_payload = {
                "rubric_association": {
                    "rubric_id": new_rid,
                    "association_type": "Assignment",
                    "association_id": int(new_asn),
                    "purpose": a.get("purpose", "grading"),
                    "use_for_grading": bool(a.get("use_for_grading", True)),
                    "hide_score_total": bool(a.get("hide_score_total", False)),
                    "hide_points": bool(a.get("hide_points", False)),
                }
            }
            try:
                canvas.post(f"/api/v1/courses/{target_course_id}/rubric_associations", json=assoc_payload)
                associated += 1
                log.debug("Associated rubric %s → assignment %s", new_rid, new_asn)
            except Exception as e:
                failed += 1
                log.warning("Failed associating rubric %s to assignment %s: %s", new_rid, new_asn, e)

    log.info(
        "Rubrics import complete",
        extra={"created": created, "associations": associated, "failed": failed, "total": len(rubrics)},
    )

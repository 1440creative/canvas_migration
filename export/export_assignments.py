# export/export_assignments.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from logging_setup import get_logger
from utils.api import CanvasAPI
from utils.fs import ensure_dir, atomic_write, json_dumps_stable, safe_relpath
from utils.strings import sanitize_slug


def export_assignments(course_id: int, export_root: Path, api: CanvasAPI) -> List[Dict[str, Any]]:
    """
    Export Canvas assignments with deterministic structure.

    Layout:
      export/data/{course_id}/assignments/{position:03d}_{slug}/index.html
                                                        └─ assignment_metadata.json

    Notes:
      - Uses CanvasAPI with normalized API root (endpoints omit /api/v1)
      - Returns list of metadata dicts (compatible with AssignmentMeta fields)
      - `module_item_ids` stays empty here; modules pass backfills it
    """
    log = get_logger(artifact="assignments", course_id=course_id)

    course_root = export_root / str(course_id)
    assigns_root = course_root / "assignments"
    ensure_dir(assigns_root)

    # 1) Fetch list (pagination handled by CanvasAPI)
    log.info("fetching assignments list", extra={"endpoint": f"courses/{course_id}/assignments"})
    items = api.get(f"courses/{course_id}/assignments", params={"per_page": 100})
    if not isinstance(items, list):
        raise TypeError("Expected list of assignments from Canvas API")

    # 2) Deterministic sort: position (fallback big), then name, then id
    def sort_key(a: Dict[str, Any]):
        pos = a.get("position") if a.get("position") is not None else 999_999
        name = (a.get("name") or "").strip()
        aid = a.get("id") or 0
        return (pos, name, aid)

    items_sorted = sorted(items, key=sort_key)

    exported: List[Dict[str, Any]] = []

    # 3) Export each assignment
    for i, a in enumerate(items_sorted, start=1):
        aid = int(a["id"])
        # Detail call: (Canvas returns same shape as list, but do it for parity/futureproofing)
        detail = api.get(f"courses/{course_id}/assignments/{aid}")
        if not isinstance(detail, dict):
            raise TypeError("Expected assignment detail dict from Canvas API")

        name = (detail.get("name") or "").strip() or f"assignment-{aid}"
        slug = sanitize_slug(name) or f"assignment-{aid}"

        a_dir = assigns_root / f"{i:03d}_{slug}"
        ensure_dir(a_dir)

        # Write an HTML representation (Canvas uses 'description' for assignment body)
        html = detail.get("description") or ""
        html_path = a_dir / "index.html"
        atomic_write(html_path, html)

        # Build metadata (align with AssignmentMeta fields)
        meta: Dict[str, Any] = {
            "id": aid,
            "name": detail.get("name"),
            "position": i,
            "published": bool(detail.get("published", True)),
            "due_at": detail.get("due_at"),  # ISO8601 or None
            "points_possible": detail.get("points_possible"),
            "html_path": safe_relpath(html_path, course_root),
            "updated_at": detail.get("updated_at") or "",
            "module_item_ids": [],  # backfilled by modules exporter
            "source_api_url": api.api_root.rstrip("/") + f"/courses/{course_id}/assignments/{aid}",
        }

        optional_fields = [
            "lock_at",
            "unlock_at",
            "grading_type",
            "submission_types",
            "allowed_attempts",
            "peer_reviews",
            "automatic_peer_reviews",
            "peer_review_count",
            "peer_reviews_assign_at",
            "group_category_id",
            "group_assignment",
            "notify_of_update",
            "muted",
            "grading_standard_id",
            "omit_from_final_grade",
            "only_visible_to_overrides",
            "moderated_grading",
            "grader_count",
            "grader_selection_strategy",
            "intra_group_peer_reviews",
            "anonymous_peer_reviews",
            "anonymous_grading",
            "grade_group_students_individually",
            "anonymous_submissions",
            "assignment_group_id",
            "external_tool_tag_attributes",
            "turnitin_enabled",
            "vericite_enabled",
        ]

        for key in optional_fields:
            if key in detail and detail[key] is not None:
                meta[key] = detail[key]

        atomic_write(a_dir / "assignment_metadata.json", json_dumps_stable(meta))
        exported.append(meta)

        log.info(
            "exported assignment",
            extra={"assignment_id": aid, "slug": slug, "position": i, "html": meta["html_path"]},
        )

    log.info("exported assignments complete", extra={"count": len(exported)})
    return exported

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from logging_setup import get_logger
from utils.api import CanvasAPI
from utils.fs import ensure_dir, atomic_write, json_dumps_stable
from utils.strings import sanitize_slug


def export_assignment_groups(course_id: int, export_root: Path, api: CanvasAPI) -> List[Dict[str, Any]]:
    """Export assignment groups and their associations for a Canvas course."""
    log = get_logger(artifact="assignment_groups", course_id=course_id)

    course_root = export_root / str(course_id)
    groups_root = course_root / "assignment_groups"
    ensure_dir(groups_root)

    log.info(
        "fetching assignment groups",
        extra={"endpoint": f"courses/{course_id}/assignment_groups"},
    )

    params = {"include[]": ["assignments", "rules"]}
    data = api.get(f"courses/{course_id}/assignment_groups", params=params)
    if not isinstance(data, list):
        raise TypeError("Expected list of assignment groups from Canvas API")

    def sort_key(group: Dict[str, Any]) -> tuple[Any, ...]:
        pos = group.get("position")
        if pos is None:
            pos = 999_999
        name = (group.get("name") or "").strip()
        gid = group.get("id") or 0
        return (pos, name, gid)

    groups_sorted = sorted(data, key=sort_key)

    exported: List[Dict[str, Any]] = []

    for index, group in enumerate(groups_sorted, start=1):
        gid = int(group["id"])
        name = (group.get("name") or "").strip() or f"assignment-group-{gid}"
        slug = sanitize_slug(name) or f"assignment-group-{gid}"

        g_dir = groups_root / f"{index:03d}_{slug}"
        ensure_dir(g_dir)

        assignments = []
        for item in group.get("assignments", []) or []:
            if isinstance(item, dict) and item.get("id") is not None:
                try:
                    assignments.append(int(item["id"]))
                except (TypeError, ValueError):
                    continue
        assignments.sort()

        meta: Dict[str, Any] = {
            "id": gid,
            "name": group.get("name"),
            "position": group.get("position"),
            "group_weight": group.get("group_weight"),
            "rules": group.get("rules"),
            "assignment_ids": assignments,
            "integration_data": group.get("integration_data"),
            "sis_source_id": group.get("sis_source_id"),
            "created_at": group.get("created_at"),
            "updated_at": group.get("updated_at"),
            "source_api_url": api.api_root.rstrip("/")
            + f"/courses/{course_id}/assignment_groups/{gid}",
        }

        # Drop keys that ended up as None to keep metadata stable
        meta = {k: v for k, v in meta.items() if v is not None and v != []}

        # Always include deterministic helpers
        meta["position"] = group.get("position")
        meta["assignment_ids"] = assignments

        atomic_write(g_dir / "assignment_group_metadata.json", json_dumps_stable(meta))
        exported.append(meta)

        log.info(
            "exported assignment group",
            extra={
                "assignment_group_id": gid,
                "slug": slug,
                "assignment_count": len(assignments),
            },
        )

    log.info("exported assignment groups complete", extra={"count": len(exported)})
    return exported

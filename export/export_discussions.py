# export/export_discussions.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from logging_setup import get_logger
from utils.api import CanvasAPI
from utils.fs import ensure_dir, atomic_write, json_dumps_stable, safe_relpath
from utils.strings import sanitize_slug


def export_discussions(course_id: int, export_root: Path, api: CanvasAPI) -> List[Dict[str, Any]]:
    """
    Export Canvas discussions with deterministic structure.

    Layout:
      export/data/{course_id}/discussions/{position:03d}_{slug}/index.html
                                                         └─ discussion_metadata.json

    Notes:
      - Uses CanvasAPI with normalized API root (endpoints omit /api/v1)
      - Returns list of metadata dicts (ready for modules backfill via `"id"`)
      - `module_item_ids` stays empty; modules pass backfills it
    """
    log = get_logger(artifact="discussions", course_id=course_id)

    course_root = export_root / str(course_id)
    disc_root = course_root / "discussions"
    ensure_dir(disc_root)

    # 1) Fetch list
    log.info("fetching discussions list", extra={"endpoint": f"courses/{course_id}/discussion_topics"})
    items = api.get(f"courses/{course_id}/discussion_topics", params={"per_page": 100})
    if not isinstance(items, list):
        raise TypeError("Expected list of discussion topics from Canvas API")

    # 2) Deterministic sort: position (fallback big), then title, then id
    def sort_key(d: Dict[str, Any]):
        pos = d.get("position") if d.get("position") is not None else 999_999
        title = (d.get("title") or "").strip()
        did = d.get("id") or 0
        return (pos, title, did)

    items_sorted = sorted(items, key=sort_key)

    exported: List[Dict[str, Any]] = []

    # 3) Export each topic
    for i, d in enumerate(items_sorted, start=1):
        did = int(d["id"])

        # Detail call (some fields only on detail)
        detail = api.get(f"courses/{course_id}/discussion_topics/{did}")
        if not isinstance(detail, dict):
            raise TypeError("Expected discussion topic detail dict from Canvas API")

        title = (detail.get("title") or f"discussion-{did}").strip()
        slug = sanitize_slug(title) or f"discussion-{did}"

        d_dir = disc_root / f"{i:03d}_{slug}"
        ensure_dir(d_dir)

        # The HTML body is under "message"
        html = detail.get("message") or ""
        html_path = d_dir / "index.html"
        atomic_write(html_path, html)

        # Build metadata (trim but useful)
        meta: Dict[str, Any] = {
            "id": did,
            "title": title,
            "position": i,
            "published": bool(detail.get("published", True)) if "published" in detail else True,
            "pinned": bool(detail.get("pinned", False)),
            "locked": bool(detail.get("locked", False)),
            "require_initial_post": bool(detail.get("require_initial_post", False)),
            "discussion_type": detail.get("discussion_type"),  # side_comment, threaded
            "posted_at": detail.get("posted_at"),
            "delayed_post_at": detail.get("delayed_post_at"),
            "last_reply_at": detail.get("last_reply_at"),
            "html_path": safe_relpath(html_path, course_root),
            "updated_at": detail.get("updated_at") or "",
            "module_item_ids": [],  # backfilled by modules exporter
            "source_api_url": api.api_root.rstrip("/") + f"/courses/{course_id}/discussion_topics/{did}",
        }

        atomic_write(d_dir / "discussion_metadata.json", json_dumps_stable(meta))
        exported.append(meta)

        log.info(
            "exported discussion",
            extra={"discussion_id": did, "slug": slug, "position": i, "html": meta["html_path"]},
        )

    log.info("exported discussions complete", extra={"count": len(exported)})
    return exported

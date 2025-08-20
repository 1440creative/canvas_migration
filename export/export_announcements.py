# export/export_announcements.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from logging_setup import get_logger
from utils.api import CanvasAPI
from utils.fs import ensure_dir, atomic_write, json_dumps_stable, safe_relpath
from utils.strings import sanitize_slug


def export_announcements(course_id: int, export_root: Path, api: CanvasAPI) -> List[Dict[str, Any]]:
    """
    Export Canvas announcements (special case of discussions).

    Layout:
      export/data/{course_id}/announcements/{position:03d}_{slug}/index.html
                                                          └─ announcement_metadata.json

    Notes:
      - Uses `only_announcements=true` param
      - Returns list of metadata dicts
    """
    log = get_logger(artifact="announcements", course_id=course_id)

    course_root = export_root / str(course_id)
    ann_root = course_root / "announcements"
    ensure_dir(ann_root)

    # 1) Fetch list (only announcements)
    log.info("fetching announcements list", extra={"endpoint": f"courses/{course_id}/discussion_topics"})
    items = api.get(
        f"courses/{course_id}/discussion_topics",
        params={"only_announcements": True, "per_page": 100},
    )
    if not isinstance(items, list):
        raise TypeError("Expected list of announcements from Canvas API")

    # 2) Deterministic sort: posted_at, then title, then id
    def sort_key(d: Dict[str, Any]):
        posted = d.get("posted_at") or ""
        title = (d.get("title") or "").strip()
        did = d.get("id") or 0
        return (posted, title, did)

    items_sorted = sorted(items, key=sort_key)

    exported: List[Dict[str, Any]] = []

    # 3) Export each announcement
    for i, d in enumerate(items_sorted, start=1):
        did = int(d["id"])

        detail = api.get(f"courses/{course_id}/discussion_topics/{did}")
        if not isinstance(detail, dict):
            raise TypeError("Expected announcement detail dict from Canvas API")

        title = (detail.get("title") or f"announcement-{did}").strip()
        slug = sanitize_slug(title) or f"announcement-{did}"

        a_dir = ann_root / f"{i:03d}_{slug}"
        ensure_dir(a_dir)

        html = detail.get("message") or ""
        html_path = a_dir / "index.html"
        atomic_write(html_path, html)

        meta: Dict[str, Any] = {
            "id": did,
            "title": title,
            "position": i,
            "published": bool(detail.get("published", True)) if "published" in detail else True,
            "pinned": bool(detail.get("pinned", False)),
            "locked": bool(detail.get("locked", False)),
            "discussion_type": detail.get("discussion_type"),
            "posted_at": detail.get("posted_at"),
            "delayed_post_at": detail.get("delayed_post_at"),
            "last_reply_at": detail.get("last_reply_at"),
            "is_announcement": True,
            "html_path": safe_relpath(html_path, course_root),
            "updated_at": detail.get("updated_at") or "",
            "module_item_ids": [],
            "source_api_url": api.api_root.rstrip("/") + f"/courses/{course_id}/discussion_topics/{did}",
        }

        atomic_write(a_dir / "announcement_metadata.json", json_dumps_stable(meta))
        exported.append(meta)

        log.info(
            "exported announcement",
            extra={"announcement_id": did, "slug": slug, "position": i, "html": meta["html_path"]},
        )

    log.info("exported announcements complete", extra={"count": len(exported)})
    return exported

# export/export_pages.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from logging_setup import get_logger
from utils.api import CanvasAPI
from utils.fs import ensure_dir, atomic_write, json_dumps_stable, safe_relpath
from utils.strings import sanitize_slug


def export_pages(course_id: int, export_root: Path, api: CanvasAPI) -> List[Dict[str, Any]]:
    """
    Export Canvas LMS pages for a course.

    - Deterministic layout:
        export/data/{course_id}/pages/{position:03d}_{slug}/index.html
                                          └─ page_metadata.json
    - Uses CanvasAPI with normalized API root (endpoints omit /api/v1).
    - Returns a list of per-page metadata dicts (compatible with PageMeta fields).
    """
    log = get_logger(artifact="pages", course_id=course_id)

    course_root = export_root / str(course_id)
    pages_root = course_root / "pages"
    ensure_dir(pages_root)

    # 1) Fetch list (pagination handled in CanvasAPI.get)
    log.info("fetching pages list", extra={"endpoint": f"courses/{course_id}/pages"})
    pages = api.get(f"courses/{course_id}/pages", params={"per_page": 100})
    if not isinstance(pages, list):
        raise TypeError("Expected list of pages from Canvas API")

    # 2) Deterministic sort: position (fallback huge), then title, then id/slug
    def sort_key(p: Dict[str, Any]):
        pos = p.get("position") if p.get("position") is not None else 999_999
        title = (p.get("title") or "").strip()
        pid = p.get("page_id") or p.get("id") or 0
        return (pos, title, pid)

    pages_sorted = sorted(pages, key=sort_key)

    exported_meta: List[Dict[str, Any]] = []

    # 3) Export each page
    for i, p in enumerate(pages_sorted, start=1):
        # Detail call for HTML + full metadata
        detail = api.get(f"courses/{course_id}/pages/{p['url']}")
        if not isinstance(detail, dict):
            raise TypeError("Expected page detail dict from Canvas API")

        slug = sanitize_slug(detail["url"])
        page_dir = pages_root / f"{i:03d}_{slug}"
        ensure_dir(page_dir)

        html = detail.get("body") or ""
        html_path = page_dir / "index.html"
        atomic_write(html_path, html)

        meta: Dict[str, Any] = {
            "id": detail.get("page_id"),
            "url": detail.get("url"),
            "title": detail.get("title"),
            "position": i,
            "module_item_ids": [],  # backfilled by modules export
            "published": bool(detail.get("published", True)),
            "updated_at": detail.get("updated_at") or "",
            "html_path": safe_relpath(html_path, course_root),  # e.g., pages/001_welcome/index.html
            "source_api_url": api.api_root.rstrip("/") + f"/courses/{course_id}/pages/{detail['url']}",
        }

        atomic_write(page_dir / "page_metadata.json", json_dumps_stable(meta))
        exported_meta.append(meta)

        log.info(
            "exported page",
            extra={"page_id": meta["id"], "slug": slug, "position": i, "html": meta["html_path"]},
        )

    log.info("exported pages complete", extra={"count": len(exported_meta)})
    return exported_meta

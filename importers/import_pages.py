# importers/import_pages.py
"""
Import Pages into a Canvas course using your CanvasAPI-style wrapper.

Expected export layout (per page directory):
    pages/<something>/
      ├─ index.html                 # page body (default filename)
      └─ page_metadata.json         # includes at least: id, title, (optional) url/slug, published, front_page

This importer:
  1) Reads page_metadata.json (+ index.html unless metadata specifies a different html file).
  2) Creates the page via POST /api/v1/courses/:course_id/pages
  3) If front_page=True, PUT to set as front page.
  4) Records mapping of old → new page IDs in id_map["pages"].
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from utils.api import CanvasAPI

log = logging.getLogger("canvas_migrations")

# module-level guard so we only warn once about ignored "position"
_WARNED_PAGE_POSITION = False


def import_pages(
    *,
    target_course_id: int,
    export_root: Path,
    canvas: CanvasAPI,
    id_map: dict[str, dict[int, int]],
) -> dict[str, int]:
    counters = {"imported": 0, "skipped": 0, "failed": 0, "total": 0}
    pages_dir = export_root / "pages"

    if not pages_dir.exists():
        log.info("course=%s artifact=pages nothing-to-import", target_course_id)
        return counters

    id_map.setdefault("pages", {})

    for page_dir in sorted(pages_dir.iterdir()):
        if not page_dir.is_dir():
            continue

        metadata_file = page_dir / "page_metadata.json"
        html_file = page_dir / "index.html"

        if not metadata_file.exists():
            log.warning(
                "course=%s artifact=pages missing_metadata dir=%s",
                target_course_id,
                page_dir,
            )
            counters["skipped"] += 1
            continue

        with metadata_file.open(encoding="utf-8") as f:
            meta: dict[str, Any] = json.load(f)

        counters["total"] += 1
        old_id = meta.get("id")

        # Guard: warn once if "position" is present (ignored on import)
        global _WARNED_PAGE_POSITION
        if "position" in meta and not _WARNED_PAGE_POSITION:
            log.warning("course=%s artifact=pages position-field-ignored", target_course_id)
            _WARNED_PAGE_POSITION = True

        # Ensure html content exists
        if not html_file.exists():
            log.warning(
                "course=%s artifact=pages missing_html page=%s",
                target_course_id,
                meta.get("title"),
            )
            counters["skipped"] += 1
            continue

        body = html_file.read_text(encoding="utf-8")

        payload = {
            "title": meta.get("title"),
            "body": body,
            "published": meta.get("published", False),
        }

        resp = canvas.post(f"/courses/{target_course_id}/pages", json=payload)
        if not resp or "url" not in resp:
            log.error(
                "course=%s artifact=pages failed-create page=%s",
                target_course_id,
                meta.get("title"),
            )
            counters["failed"] += 1
            continue

        new_url = resp["url"]
        new_id = resp.get("page_id") or 0
        if old_id is not None:
            id_map["pages"][old_id] = new_id

        counters["imported"] += 1

        if meta.get("front_page"):
            put_resp = canvas.put(f"/courses/{target_course_id}/pages/{new_url}")
            if not put_resp:
                log.error(
                    "course=%s artifact=pages failed-frontpage page=%s",
                    target_course_id,
                    new_url,
                )
                counters["failed"] += 1

    log.info(
        "course=%s artifact=pages Pages import complete. imported=%s skipped=%s failed=%s total=%s",
        target_course_id,
        counters["imported"],
        counters["skipped"],
        counters["failed"],
        counters["total"],
    )
    return counters

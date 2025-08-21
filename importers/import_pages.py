# importers/import_pages.py
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from utils.api import CanvasAPI

log = logging.getLogger("canvas_migrations")

_WARNED_PAGE_POSITION = False


def import_pages(
    *,
    target_course_id: int,
    export_root: Path,
    canvas: CanvasAPI,
    id_map: dict[str, dict],
) -> dict[str, int]:
    counters = {"imported": 0, "skipped": 0, "failed": 0, "total": 0}
    pages_dir = export_root / "pages"

    if not pages_dir.exists():
        log.info("course=%s artifact=pages nothing-to-import", target_course_id)
        return counters

    id_map.setdefault("pages", {})
    id_map.setdefault("pages_url", {})

    for page_dir in sorted(pages_dir.iterdir()):
        if not page_dir.is_dir():
            continue

        metadata_file = page_dir / "page_metadata.json"
        html_file = page_dir / "index.html"
        if not metadata_file.exists():
            log.warning("course=%s artifact=pages missing_metadata dir=%s", target_course_id, page_dir)
            counters["skipped"] += 1
            continue

        meta: dict[str, Any] = json.loads(metadata_file.read_text(encoding="utf-8"))

        counters["total"] += 1
        old_id = meta.get("id")
        old_url = meta.get("url")

        global _WARNED_PAGE_POSITION
        if "position" in meta and not _WARNED_PAGE_POSITION:
            log.warning("course=%s artifact=pages position-field-ignored", target_course_id)
            _WARNED_PAGE_POSITION = True

        if not html_file.exists():
            alt_file = page_dir / "body.html"
            if alt_file.exists():
                html_file = alt_file
            else:
                log.warning("course=%s artifact=pages missing_html page=%s", target_course_id, meta.get("title"))
                counters["skipped"] += 1
                continue

        body = html_file.read_text(encoding="utf-8")
        payload = {"title": meta.get("title"), "body": body, "published": meta.get("published", False)}

        # unwrap response
        resp = canvas.post(f"/courses/{target_course_id}/pages", json=payload)
        resp_data = resp.json() if hasattr(resp, "json") else resp

        if not resp_data or "url" not in resp_data:
            log.error("course=%s artifact=pages failed-create page=%s", target_course_id, meta.get("title"))
            counters["failed"] += 1
            continue

        new_url = resp_data["url"]
        new_id = resp_data.get("page_id")

        if old_id is not None and new_id:
            id_map["pages"][old_id] = new_id
        if old_url:
            id_map["pages_url"][old_url] = new_url

        counters["imported"] += 1

        if meta.get("front_page"):
            put_resp = canvas.put(f"/courses/{target_course_id}/pages/{new_url}", json={"front_page": True})
            put_data = put_resp.json() if hasattr(put_resp, "json") else put_resp
            if not put_data:
                log.error("course=%s artifact=pages failed-frontpage page=%s", target_course_id, new_url)
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

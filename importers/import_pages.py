# importers/import_pages.py
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger("canvas_migrations")

# Warn only once per run if exported position != server position
_POSITION_MISMATCH_WARNED = False


def import_pages(
    *,
    target_course_id: int,
    export_root: Path,
    canvas,  # CanvasAPI-like (needs: post, put, session.get)
    id_map: dict[str, dict],
) -> dict[str, int]:
    """
    Import wiki pages:
      - POST /courses/:id/pages with title/body/published
      - If POST returns only slug + Location, GET the Location to obtain numeric id
      - Always record pages_url[old_slug] -> new_slug; record pages[old_id] -> new_id when available
      - If front_page: True, PUT /courses/:id/front_page after creation
      - If exported 'position' differs from server 'position', log a single 'position mismatch' warning
    """
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
        old_slug = meta.get("url") or None

        if not html_file.exists():
            alt_file = page_dir / "body.html"
            if alt_file.exists():
                html_file = alt_file
            else:
                log.warning("course=%s artifact=pages missing_html page=%s", target_course_id, meta.get("title"))
                counters["skipped"] += 1
                continue

        body = html_file.read_text(encoding="utf-8")
        payload = {
            "title": meta.get("title"),
            "body": body,
            "published": meta.get("published", False),
        }

        # --- Create page
        try:
            resp = canvas.post(f"/courses/{target_course_id}/pages", json=payload)
            # Try to parse JSON; tolerate empty/non-JSON
            try:
                data = resp.json()
            except Exception:
                data = {}
        except Exception as e:
            counters["failed"] += 1
            log.exception("course=%s artifact=pages failed-create-exception page=%s: %s",
                          target_course_id, meta.get("title"), e)
            continue

        new_slug = data.get("url")
        new_id = data.get("id") or data.get("page_id")

        # If we don't have an id but a Location header exists, follow it to fetch id (+canonical slug)
        if not new_id and "Location" in getattr(resp, "headers", {}):
            try:
                follow = canvas.session.get(resp.headers["Location"])
                follow.raise_for_status()
                try:
                    j2 = follow.json()
                except Exception:
                    j2 = {}
                new_id = j2.get("id") or j2.get("page_id") or new_id
                new_slug = j2.get("url") or new_slug
            except Exception as e:
                # We'll still record slug mapping below if we have it
                log.debug("course=%s artifact=pages follow-location failed: %s", target_course_id, e)

        if not new_slug:
            counters["failed"] += 1
            log.error("course=%s artifact=pages failed-create page=%s (no slug returned)",
                      target_course_id, meta.get("title"))
            continue

        # --- Update id maps
        if old_slug:
            id_map["pages_url"][old_slug] = new_slug
        if old_id is not None and new_id:
            try:
                id_map["pages"][int(old_id)] = int(new_id)
            except Exception:
                pass

        # --- Position mismatch warning (once)
        exp_pos = meta.get("position")
        got_pos = data.get("position")
        # If we followed Location, prefer the followed response for position
        if not got_pos and 'j2' in locals():
            got_pos = j2.get("position")

        global _POSITION_MISMATCH_WARNED
        if exp_pos is not None and got_pos is not None and exp_pos != got_pos and not _POSITION_MISMATCH_WARNED:
            log.warning("course=%s artifact=pages position mismatch: exported=%s server=%s slug=%s",
                        target_course_id, exp_pos, got_pos, new_slug)
            _POSITION_MISMATCH_WARNED = True

        counters["imported"] += 1

        # --- Front page: set after creation via /front_page
        if meta.get("front_page"):
            try:
                canvas.put(f"/courses/{target_course_id}/front_page", json={"url": new_slug})
            except Exception as e:
                counters["failed"] += 1
                log.error("course=%s artifact=pages failed-frontpage slug=%s: %s", target_course_id, new_slug, e)

    log.info(
        "course=%s artifact=pages Pages import complete. imported=%s skipped=%s failed=%s total=%s",
        target_course_id, counters["imported"], counters["skipped"], counters["failed"], counters["total"],
    )
    return counters
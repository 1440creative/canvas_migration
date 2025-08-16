# importers/import_pages.py
"""
Import Pages into a Canvas course using your CanvasAPI-style wrapper.

Expected export layout (per page directory):
    pages/<something>/
      ├─ index.html                 # page body (default filename)
      └─ page_metadata.json         # includes at least: id, title, (optional) url/slug, published, front_page

This importer:
  1) Reads page_metadata.json (+ index.html unless metadata specifies a different html file).
  2) Creates the page via POST /api/v1/courses/{course_id}/pages.
  3) If front_page==True, sets it on the created page via PUT /api/v1/courses/{course_id}/pages/{url}.
  4) Records:
        id_map["pages"][old_id]      = new_page_id   (if Canvas returns a numeric page_id)
        id_map["pages_url"][old_url] = new_url       (slug-to-slug mapping for modules)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, Optional, Protocol

from logging_setup import get_logger
import requests


def _resolve_html_file(page_dir: Path, meta: dict, course_root: Path) -> Path | None:
    # 1) Prefer metadata html_path if it points to a real file (relative to course_root)
    html_rel = (meta or {}).get("html_path")
    if html_rel:
        p = (course_root / html_rel)
        if p.exists():
            return p

    # 2) Look for common filenames inside this page directory
    for name in ("index.html", "body.html", "description.html", "page.html"):
        p = page_dir / name
        if p.exists():
            return p

    # 3) Last resort: if there’s exactly one *.htm(l) file, use it
    htmls = list(page_dir.glob("*.htm*"))
    if len(htmls) == 1:
        return htmls[0]

    return None


__all__ = ["import_pages"]


# ---- Protocol to decouple from your exact CanvasAPI class -------------------
class CanvasLike(Protocol):
    session: requests.Session
    api_root: str  # e.g., "https://school.instructure.com/api/v1/"

    def post(self, endpoint: str, **kwargs) -> requests.Response: ...
    def put(self, endpoint: str, **kwargs) -> requests.Response: ...
    def post_json(self, endpoint: str, *, payload: Dict[str, Any]) -> Dict[str, Any]: ...


# ---- Helpers ----------------------------------------------------------------
def _read_text(path: Path) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def _coerce_int(val: Any) -> Optional[int]:
    try:
        return int(val) if val is not None else None
    except (TypeError, ValueError):
        return None


# ---- Public entrypoint ------------------------------------------------------
def import_pages(
    *,
    target_course_id: int,
    export_root: Path,
    canvas: CanvasLike,
    id_map: Dict[str, Dict[Any, Any]],
    on_duplicate_title: str = "allow",  # reserved for future (Canvas handles by slug)
) -> None:
    """
    Create pages from export_root/pages into the target course and update id_map.

    Produces/updates:
        id_map["pages"]     : Dict[int(old_page_id) -> int(new_page_id)]
        id_map["pages_url"] : Dict[str(old_url_slug) -> str(new_url_slug)]
    """
    logger = get_logger(course_id=target_course_id, artifact="pages")

    pages_dir = export_root / "pages"
    if not pages_dir.exists():
        logger.warning("No pages directory found at %s", pages_dir)
        return

    logger.info("Starting pages import from %s", pages_dir)

    page_id_map = id_map.setdefault("pages", {})
    page_url_map = id_map.setdefault("pages_url", {})

    imported = 0
    skipped = 0
    failed = 0

    course_root = export_root if isinstance(export_root, Path) else Path(export_root)

    for meta_file in pages_dir.rglob("page_metadata.json"):
        page_dir = meta_file.parent

        try:
            metadata = json.loads(_read_text(meta_file))
        except Exception as e:
            failed += 1
            logger.exception("Failed to read %s: %s", meta_file, e)
            continue

        old_id = _coerce_int(metadata.get("id"))
        title = metadata.get("title") or metadata.get("page_title")
        old_url = metadata.get("url") or metadata.get("slug")

        # Resolve HTML body file (new + old export layouts)
        html_path = _resolve_html_file(page_dir, metadata, course_root)
        if not html_path:
            skipped += 1
            logger.warning("Skipping page at %s (missing HTML body file)", page_dir)
            continue

        if not title:
            skipped += 1
            logger.warning("Skipping %s (missing page title)", meta_file)
            continue

        html = _read_text(html_path)
        published = bool(metadata.get("published", True))   # default True matches export side
        is_front_page = bool(metadata.get("front_page", False))

        try:
            # ---- POST create page (Canvas expects 'wiki_page' envelope)
            payload = {
                "wiki_page": {
                    "title": title,
                    "body": html,
                    "published": published,
                }
            }
            new_page = canvas.post_json(
                f"/api/v1/courses/{target_course_id}/pages",
                payload=payload,
            )

            # Canvas returns at least 'url' (slug); sometimes 'page_id'
            new_url = new_page.get("url") or new_page.get("slug")
            new_page_id = _coerce_int(new_page.get("page_id") or new_page.get("id"))

            if old_id is not None and new_page_id is not None:
                page_id_map[old_id] = new_page_id
            if old_url and new_url:
                page_url_map[str(old_url)] = str(new_url)

            # Mark front page if requested
            if is_front_page and new_url:
                _set_front_page(canvas=canvas, course_id=target_course_id, url=new_url)

            imported += 1
            logger.info("Created page '%s' (url=%s, id=%s)", title, new_url, new_page_id)

        except Exception as e:
            failed += 1
            logger.exception("Failed to create page from %s: %s", page_dir, e)

    logger.info(
        "Pages import complete. imported=%d skipped=%d failed=%d total=%d",
        imported, skipped, failed, imported + skipped + failed
    )


# ---- Canvas ops -------------------------------------------------------------
def _set_front_page(
    *,
    canvas: CanvasLike,
    course_id: int,
    url: str,
) -> None:
    """
    Mark a page as the course front page:
    PUT /courses/{course_id}/pages/{url} with {"wiki_page": {"front_page": true}}.
    """
    payload = {"wiki_page": {"front_page": True}}
    resp = canvas.put(f"/api/v1/courses/{course_id}/pages/{url}", json=payload)
    resp.raise_for_status()

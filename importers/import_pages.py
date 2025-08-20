from __future__ import annotations

import json
import requests

from pathlib import Path
from typing import Dict, Any, Optional, Protocol

from logging_setup import get_logger
from models import PageMeta
from utils.mapping import record_mapping

_WARNED_PAGE_POSITION = False


def _resolve_html_file(page_dir: Path, meta: PageMeta, course_root: Path) -> Path | None:
    if meta.html_path:
        p = course_root / meta.html_path
        if p.exists():
            return p

    for name in ("index.html", "body.html", "description.html", "page.html"):
        p = page_dir / name
        if p.exists():
            return p

    htmls = list(page_dir.glob("*.htm*"))
    if len(htmls) == 1:
        return htmls[0]

    return None


__all__ = ["import_pages"]


class CanvasLike(Protocol):
    session: requests.Session
    api_root: str

    def post(self, endpoint: str, **kwargs) -> requests.Response: ...
    def put(self, endpoint: str, **kwargs) -> requests.Response: ...
    def post_json(self, endpoint: str, *, payload: Dict[str, Any]) -> Dict[str, Any]: ...


def _read_text(path: Path) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _coerce_int(val: Any) -> Optional[int]:
    try:
        return int(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def import_pages(
    *,
    target_course_id: int,
    export_root: Path,
    canvas: CanvasLike,
    id_map: Dict[str, Dict[Any, Any]],
    on_duplicate_title: str = "allow",
) -> None:
    logger = get_logger(course_id=target_course_id, artifact="pages")

    pages_dir = export_root / "pages"
    if not pages_dir.exists():
        logger.warning("No pages directory found at %s", pages_dir)
        return

    logger.info("Starting pages import from %s", pages_dir)

    page_id_map = id_map.setdefault("pages", {})
    page_url_map = id_map.setdefault("pages_url", {})

    imported = skipped = failed = 0
    course_root = Path(export_root)

    for meta_file in pages_dir.rglob("page_metadata.json"):
        page_dir = meta_file.parent
        try:
            metadata_dict = json.loads(_read_text(meta_file))
            meta = PageMeta(**metadata_dict)
        except Exception as e:
            failed += 1
            logger.exception("Failed to read %s: %s", meta_file, e)
            continue

        global _WARNED_PAGE_POSITION
        if not _WARNED_PAGE_POSITION and getattr(meta, "position", None) is not None:
            logger.debug(
                "Ignoring PageMeta.position; Canvas has no global Pages order. "
                "ModuleItemMeta.position governs ordering within modules."
            )
            _WARNED_PAGE_POSITION = True

        old_id = _coerce_int(meta.id)
        old_url = meta.url
        title = meta.title

        html_path = _resolve_html_file(page_dir, meta, course_root)
        if not html_path:
            skipped += 1
            logger.warning("Skipping page at %s (missing HTML body file)", page_dir)
            continue

        if not title:
            skipped += 1
            logger.warning("Skipping %s (missing page title)", meta_file)
            continue

        html = _read_text(html_path)
        published = bool(meta.published if meta.published is not None else True)
        is_front_page = bool(meta.front_page)

        try:
            payload = {"wiki_page": {"title": title, "body": html, "published": published}}
            new_page = canvas.post_json(
                f"/api/v1/courses/{target_course_id}/pages", payload=payload
            )

            new_url = new_page.get("url") or new_page.get("slug")
            new_page_id = _coerce_int(new_page.get("page_id") or new_page.get("id"))

            record_mapping(
                old_id=old_id,
                new_id=new_page_id,
                old_slug=old_url,
                new_slug=new_url,
                id_map=page_id_map,
                slug_map=page_url_map,
            )

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


def _set_front_page(*, canvas: CanvasLike, course_id: int, url: str) -> None:
    payload = {"wiki_page": {"front_page": True}}
    resp = canvas.put(f"/api/v1/courses/{course_id}/pages/{url}", json=payload)
    resp.raise_for_status()

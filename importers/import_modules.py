# importers/import_modules.py
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Protocol, Tuple

import requests
from logging_setup import get_logger

__all__ = ["import_modules"]


class CanvasLike(Protocol):
    session: requests.Session
    api_root: str
    def get(self, endpoint: str, **kwargs) -> requests.Response: ...
    def post(self, endpoint: str, **kwargs) -> requests.Response: ...
    def put(self, endpoint: str, **kwargs) -> requests.Response: ...


def _read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _coerce_int(val: Any) -> Optional[int]:
    try:
        return int(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _follow_location_for_id(canvas: CanvasLike, resp: requests.Response, key: str = "id") -> Optional[int]:
    if "Location" not in resp.headers:
        return None
    try:
        r2 = canvas.session.get(resp.headers["Location"])
        r2.raise_for_status()
        j = r2.json()
        return _coerce_int(j.get(key))
    except Exception:
        return None


def _build_item_payload(item: Dict[str, Any], id_map: Dict[str, Dict[Any, Any]]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Returns (payload, skip_reason)
    Maps exported item to Canvas module_item payload. If mapping is missing, returns (None, reason).
    """
    t = (item.get("type") or "").strip()
    title = item.get("title")
    indent = item.get("indent") or 0
    published = bool(item.get("published", False))

    payload: Dict[str, Any] = {"module_item": {"type": None}}  # fill below
    mi = payload["module_item"]

    def mapped_id(kind: str, old: Any) -> Optional[int]:
        old_i = _coerce_int(old)
        return id_map.get(kind, {}).get(old_i) if old_i is not None else None

    if t == "Page":
        # Prefer explicit page_url in export; otherwise map by old slug or id
        old_slug = item.get("page_url") or item.get("url") or item.get("slug")
        new_slug = None
        if old_slug:
            new_slug = id_map.get("pages_url", {}).get(str(old_slug))
        if not new_slug and item.get("content_id") is not None:
            # We only have new numeric id; Canvas needs page_url,
            # so without slug mapping we can't safely create this item.
            return None, "missing pages_url mapping for Page"
        if not new_slug:
            return None, "no page_url available for Page"
        mi.update({"type": "Page", "page_url": new_slug})
        if title:
            mi["title"] = title

    elif t in ("Assignment", "Discussion", "Quiz", "File"):
        kind_key = {
            "Assignment": "assignments",
            "Discussion": "discussions",
            "Quiz": "quizzes",
            "File": "files",
        }[t]
        old_id = item.get("content_id") or item.get("id")  # exporter may use either
        new_id = mapped_id(kind_key, old_id)
        if new_id is None:
            return None, f"missing id_map for {t} ({old_id})"
        mi.update({"type": t, "content_id": new_id})
        if title:
            mi["title"] = title

    elif t in ("ExternalUrl", "ExternalURL"):
        url = item.get("external_url") or item.get("url")
        if not url:
            return None, "ExternalUrl missing url"
        mi.update({"type": "ExternalUrl", "external_url": url})
        if title:
            mi["title"] = title
        if item.get("new_tab") is not None:
            mi["new_tab"] = bool(item["new_tab"])

    elif t in ("ExternalTool", "Lti"):
        url = item.get("external_url") or item.get("url")
        if not url:
            return None, "ExternalTool missing url"
        mi.update({
            "type": "ExternalTool",
            "external_tool_tag_attributes": {"url": url, "new_tab": bool(item.get("new_tab", False))}
        })
        if title:
            mi["title"] = title

    elif t in ("SubHeader", "Header"):
        mi.update({"type": "SubHeader", "title": title or "—"})

    else:
        return None, f"unsupported type '{t}'"

    # Common attributes
    mi["indent"] = indent
    mi["published"] = published
    return payload, None


def import_modules(
    *,
    target_course_id: int,
    export_root: Path,
    canvas: CanvasLike,
    id_map: Dict[str, Dict[Any, Any]],
) -> Dict[str, int]:
    """
    Import course modules and their items using modules.json produced by the exporter.

    - Creates each module: POST /courses/:id/modules { module: { name, published } }
    - Creates items in order with explicit positions: POST /courses/:id/modules/:module_id/items { module_item: {..., position} }
    - Resolves cross-refs via id_map:
        pages_url (old_slug -> new_slug), assignments, discussions, quizzes, files (old_id -> new_id)
    - Skips items whose mapping isn't available (logs a warning), continues with others.
    """
    log = get_logger(course_id=target_course_id, artifact="modules")
    counters = {
        "modules_created": 0,
        "modules_failed": 0,
        "items_created": 0,
        "items_skipped": 0,
        "items_failed": 0,
        "total_modules": 0,
    }

    modules_path = export_root / "modules" / "modules.json"
    if not modules_path.exists():
        log.info("no modules.json found at %s", modules_path)
        return counters

    try:
        modules_data = _read_json(modules_path) or []
    except Exception as e:
        log.exception("failed to read %s: %s", modules_path, e)
        return counters

    if not isinstance(modules_data, list):
        log.error("modules.json is not a list")
        return counters

    # Safety limiter for quick live tests
    limit = _coerce_int(os.getenv("IMPORT_MODULES_LIMIT")) or None
    if limit:
        log.info("IMPORT_MODULES_LIMIT=%s active", limit)

    for idx, m in enumerate(modules_data, start=1):
        counters["total_modules"] += 1
        if limit and counters["modules_created"] >= limit:
            log.info("IMPORT_MODULES_LIMIT reached; stopping early")
            break

        name = m.get("name") or f"Module {idx}"
        published = bool(m.get("published", False))

        payload = {"module": {"name": name, "published": published}}
        log.debug("create module name=%r", name)

        try:
            resp = canvas.post(f"/api/v1/courses/{target_course_id}/modules", json=payload)
            data = {}
            try:
                data = resp.json()
            except ValueError:
                pass
            module_id = _coerce_int(data.get("id")) or _follow_location_for_id(canvas, resp, key="id")
            if not module_id:
                counters["modules_failed"] += 1
                log.error("failed to create module (no id) name=%r", name)
                continue
        except Exception as e:
            counters["modules_failed"] += 1
            log.exception("failed-create module name=%r: %s", name, e)
            continue

        counters["modules_created"] += 1

        # Items
        items = m.get("items") or []
        for pos, item in enumerate(items, start=1):
            payload_item, reason = _build_item_payload(item, id_map)
            if payload_item is None:
                counters["items_skipped"] += 1
                log.warning("skip item in module=%r reason=%s item=%s", name, reason, item.get("title"))
                continue
            # keep order by passing position
            payload_item["module_item"]["position"] = pos
            try:
                canvas.post(f"/api/v1/courses/{target_course_id}/modules/{module_id}/items", json=payload_item)
                counters["items_created"] += 1
            except Exception as e:
                counters["items_failed"] += 1
                log.exception("failed-create item module=%r title=%r: %s", name, item.get("title"), e)

    log.info(
        "Modules import complete. modules_created=%d items_created=%d items_skipped=%d items_failed=%d modules_failed=%d total_modules=%d",
        counters["modules_created"], counters["items_created"], counters["items_skipped"],
        counters["items_failed"], counters["modules_failed"], counters["total_modules"]
    )
    return counters

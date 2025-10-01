# importers/import_modules.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

from logging_setup import get_logger

log = get_logger(artifact="modules", course_id="-")


def _read_json(p: Path) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _resp_json(resp: Any) -> dict:
    """
    Robust JSON extraction from real responses or test doubles.
    """
    # 1) requests.Response with .json() method
    if hasattr(resp, "json") and callable(getattr(resp, "json", None)):
        try:
            j = resp.json()
            if isinstance(j, dict):
                return j
        except Exception:
            pass

    # 2) Some fakes set .json as a dict attribute
    maybe_dict = getattr(resp, "json", None)
    if isinstance(maybe_dict, dict):
        return maybe_dict

    # 3) Already a dict
    if isinstance(resp, dict):
        return resp

    # 4) .text with JSON
    text = getattr(resp, "text", None)
    if isinstance(text, str) and text:
        try:
            j = json.loads(text)
            if isinstance(j, dict):
                return j
        except Exception:
            pass

    # 5) _content with JSON
    raw = getattr(resp, "_content", None)
    if isinstance(raw, (bytes, bytearray)) and raw:
        try:
            j = json.loads(raw.decode("utf-8", errors="ignore"))
            if isinstance(j, dict):
                return j
        except Exception:
            pass

    return {}


def _follow_location_for_id(canvas, loc_url: str) -> Optional[int]:
    try:
        r = canvas.session.get(loc_url)
        r.raise_for_status()
        body = _resp_json(r)
        mid = body.get("id")
        return int(mid) if isinstance(mid, int) else None
    except Exception:
        return None


def _extract_module_id(canvas, resp: Any) -> Optional[int]:
    body = _resp_json(resp)
    if isinstance(body.get("id"), int):
        return int(body["id"])
    headers = getattr(resp, "headers", {}) if hasattr(resp, "headers") else {}
    loc = headers.get("Location")
    if loc:
        return _follow_location_for_id(canvas, loc)
    return None


def _make_item_payload(
    item: Dict[str, Any],
    *,
    id_map: Dict[str, Dict[Any, Any]],
    position: int,
) -> Tuple[Optional[dict], Optional[str]]:
    """
    Build {"module_item": {...}} for one item or return (None, reason) to skip.
    """
    t = (item.get("type") or "").strip()
    title = item.get("title") or ""
    published = bool(item.get("published", False))

    if t == "Page":
        src_slug = item.get("page_url")
        if not src_slug:
            return (None, "missing page_url")
        tgt_slug = id_map.get("pages_url", {}).get(src_slug)
        if not tgt_slug:
            return (None, "no pages_url mapping")
        return ({
            "module_item": {
                "type": "Page",
                "title": title,
                "page_url": tgt_slug,
                "published": published,
                "position": position,
            }
        }, None)

    if t == "Assignment":
        src_id = item.get("content_id")
        if src_id is None:
            return (None, "missing content_id")
        new_id = id_map.get("assignments", {}).get(src_id)
        if not isinstance(new_id, int):
            return (None, "no assignment id mapping")
        return ({
            "module_item": {
                "type": "Assignment",
                "title": title,
                "content_id": new_id,
                "published": published,
                "position": position,
            }
        }, None)

    if t == "Quiz":
        src_id = item.get("content_id")
        if src_id is None:
            return (None, "missing content_id")
        new_id = id_map.get("quizzes", {}).get(src_id)
        if not isinstance(new_id, int):
            return (None, "no quiz id mapping")
        return ({
            "module_item": {
                "type": "Quiz",
                "title": title,
                "content_id": new_id,
                "published": published,
                "position": position,
            }
        }, None)

    if t in {"Discussion", "DiscussionTopic"}:
        src_id = item.get("content_id")
        if src_id is None:
            return (None, "missing content_id")
        new_id = id_map.get("discussions", {}).get(src_id)
        if not isinstance(new_id, int):
            return (None, "no discussion id mapping")
        return ({
            "module_item": {
                "type": "Discussion",
                "title": title,
                "content_id": new_id,
                "published": published,
                "position": position,
            }
        }, None)

    if t == "SubHeader":
        if not title:
            return (None, "missing title")
        return ({
            "module_item": {
                "type": "SubHeader",
                "title": title,
                "published": published,
                "position": position,
            }
        }, None)

    if t == "ExternalUrl":
        ext = item.get("external_url")
        if not ext:
            return (None, "missing external_url")
        return ({
            "module_item": {
                "type": "ExternalUrl",
                "title": title,
                "external_url": ext,
                "published": published,
                "position": position,
            }
        }, None)

    return (None, f"unsupported type {t!r}")


def import_modules(
    *,
    target_course_id: int,
    export_root: Path,
    canvas,
    id_map: Dict[str, Dict[Any, Any]],
) -> Dict[str, int]:
    """
    Create modules from export/modules/modules.json and add items using id_map.

    Uses ABSOLUTE URLs with canvas.session so requests_mock matches exactly.
    """
    modules_path = export_root / "modules" / "modules.json"
    data = _read_json(modules_path) or []
    if not isinstance(data, list):
        data = []

    counters = {
        "modules_created": 0,
        "modules_failed": 0,
        "items_created": 0,
        "items_failed": 0,
        "items_skipped": 0,
        "total_modules": len(data),
    }

    # Ensure expected id_map buckets exist
    id_map.setdefault("modules", {})
    id_map.setdefault("pages_url", {})
    id_map.setdefault("assignments", {})
    id_map.setdefault("quizzes", {})
    id_map.setdefault("discussions", {})

    api_root = (getattr(canvas, "api_root", "") or "").rstrip("/")

    for m in data:
        name = (m or {}).get("name") or "Untitled Module"
        mod_payload = {"name": name}
        if (m or {}).get("published") is not None:
            mod_payload["published"] = bool(m.get("published"))

        try:
            # Use ABSOLUTE URL so requests_mock matches test setup
            create_url = f"{api_root}/api/v1/courses/{target_course_id}/modules" if api_root else f"/api/v1/courses/{target_course_id}/modules"
            resp = canvas.session.post(create_url, json={"module": mod_payload})
        except Exception as e:
            log.error("failed to create module name=%r error=%s", name, e)
            counters["modules_failed"] += 1
            continue

        new_mod_id = _extract_module_id(canvas, resp)
        if not isinstance(new_mod_id, int):
            log.error("failed to create module (no id) name=%r", name)
            counters["modules_failed"] += 1
            continue

        counters["modules_created"] += 1
        src_mod_id = (m or {}).get("id")
        if isinstance(src_mod_id, int):
            id_map["modules"][src_mod_id] = new_mod_id

        # Items
        items = (m or {}).get("items") or []
        position = 1
        for item in items:
            payload, skip_reason = _make_item_payload(item, id_map=id_map, position=position)
            if skip_reason:
                counters["items_skipped"] += 1
                position += 1
                continue

            try:
                items_url = f"{api_root}/api/v1/courses/{target_course_id}/modules/{new_mod_id}/items" if api_root else f"/api/v1/courses/{target_course_id}/modules/{new_mod_id}/items"
                r_item = canvas.session.post(items_url, json=payload)
                body = _resp_json(r_item)
                if isinstance(body.get("id"), int):
                    counters["items_created"] += 1
                else:
                    counters["items_failed"] += 1
            except Exception:
                counters["items_failed"] += 1
            finally:
                position += 1

    log.info(
        "Modules import complete. modules_created=%d modules_failed=%d items_created=%d items_skipped=%d items_failed=%d total_modules=%d",
        counters["modules_created"],
        counters["modules_failed"],
        counters["items_created"],
        counters["items_skipped"],
        counters["items_failed"],
        counters["total_modules"],
    )
    return counters

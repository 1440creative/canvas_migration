#import/import_modules.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from logging_setup import get_logger
from utils.api import CanvasAPI


def _sorted_modules(modules: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deterministic order: (position, id)."""
    return sorted(
        modules,
        key=lambda m: (
            int(m.get("position", 10_000_000)),
            int(m.get("id", 0)),
        ),
    )


def _sorted_items(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deterministic order: (position, title, id)."""
    return sorted(
        items,
        key=lambda i: (
            int(i.get("position", 10_000_000)),
            str(i.get("title", "")),
            int(i.get("id", 0)),
        ),
    )


def _module_payload(meta: Dict[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "module": {
            "name": meta.get("name", "Untitled Module"),
            "position": meta.get("position"),
            "published": bool(meta.get("published", False)),
            "require_sequential_progress": bool(
                meta.get("require_sequential_progress", False)
            ),
        }
    }
    # Optional timestamp field
    if meta.get("unlock_at"):
        payload["module"]["unlock_at"] = meta["unlock_at"]
    return payload


def _build_item_payload(
    item: Dict[str, Any],
    id_map: Dict[str, Dict[Any, Any]],
) -> Tuple[Dict[str, Any] | None, str | None]:
    """
    Return (payload, warn_msg). If a required mapping is missing,
    returns (None, warning_string).
    """
    t = item.get("type")
    title = item.get("title")
    base = {
        "type": t,
        # Canvas will position sequentially if omitted, but including
        # position helps tests assert determinism.
        "position": item.get("position"),
        "indent": item.get("indent", 0),
        "published": bool(item.get("published", True)),
    }

    # Common helper to return payload
    def ok(extra: Dict[str, Any]) -> Tuple[Dict[str, Any], None]:
        p = {"module_item": {**base, **extra}}
        # Title is ignored for some types but is harmless and useful for tests
        if title and "title" not in p["module_item"]:
            p["module_item"]["title"] = title
        return p, None

    # Type-specific handling
    if t == "Page":
        old_slug = item.get("page_url") or item.get("url") or item.get("page_slug")
        new_slug = None
        if old_slug is not None:
            new_slug = id_map.get("pages_url", {}).get(old_slug)
        if not new_slug:
            return None, f"missing pages_url mapping for page slug '{old_slug}'"
        return ok({"page_url": new_slug})

    if t == "Assignment":
        old_id = item.get("content_id") or item.get("assignment_id") or item.get("id")
        new_id = id_map.get("assignments", {}).get(old_id)
        if new_id is None:
            return None, f"missing assignments mapping for id {old_id}"
        return ok({"content_id": new_id})

    if t == "Discussion":
        old_id = item.get("content_id") or item.get("discussion_id") or item.get("id")
        new_id = id_map.get("discussions", {}).get(old_id)
        if new_id is None:
            return None, f"missing discussions mapping for id {old_id}"
        return ok({"content_id": new_id})

    if t == "Quiz":
        old_id = item.get("content_id") or item.get("quiz_id") or item.get("id")
        new_id = id_map.get("quizzes", {}).get(old_id)
        if new_id is None:
            return None, f"missing quizzes mapping for id {old_id}"
        return ok({"content_id": new_id})

    if t == "File":
        old_id = item.get("content_id") or item.get("file_id") or item.get("id")
        new_id = id_map.get("files", {}).get(old_id)
        if new_id is None:
            return None, f"missing files mapping for id {old_id}"
        return ok({"content_id": new_id})

    if t == "ExternalUrl":
        url = item.get("external_url") or item.get("url")
        if not url:
            return None, "ExternalUrl item missing 'external_url'"
        new_tab = item.get("new_tab")
        extra = {"external_url": url}
        if isinstance(new_tab, bool):
            extra["new_tab"] = new_tab
        # Title is meaningful here; ensure present
        if title:
            extra["title"] = title
        return ok(extra)

    if t == "ExternalTool":
        url = item.get("external_tool_url") or item.get("url")
        if not url:
            return None, "ExternalTool item missing 'external_tool_url'"
        new_tab = item.get("new_tab")
        extra = {"external_tool_url": url}
        if isinstance(new_tab, bool):
            extra["new_tab"] = new_tab
        if title:
            extra["title"] = title
        return ok(extra)

    if t == "SubHeader":
        # Canvas expects just title/position/indent/published for SubHeader
        return ok({"title": title or "—"})

    # Unknown type — skip with warning
    return None, f"unknown module item type '{t}'"


def import_modules(
    target_course_id: int,
    export_root: Path,
    canvas: CanvasAPI,
    id_map: Dict[str, Dict[Any, Any]],
) -> None:
    """
    Import Modules for a target course using exported metadata and existing ID maps.

    Assumptions:
    - Export layout: export/data/{source_course_id}/modules/modules.json
    - id_map contains: files, pages_url, assignments, quizzes, discussions (and we fill modules)
    """
    logger = get_logger(course_id=target_course_id, artifact="modules")

    modules_path = export_root / "modules" / "modules.json"
    if not modules_path.exists():
        logger.warning("No modules.json found at %s — skipping modules import", modules_path)
        return

    import json
    modules_data = json.loads(modules_path.read_text())
    modules = _sorted_modules(modules_data)
    logger.info("Importing %d modules from %s", len(modules), modules_path)

    # Ensure id_map key
    id_map.setdefault("modules", {})

    # Create each module
    for m in modules:
        old_module_id = m.get("id")
        payload = _module_payload(m)
        logger.debug("Creating module %s (old_id=%s) with payload=%s", m.get("name"), old_module_id, payload)

        resp = canvas.post_json(f"/courses/{target_course_id}/modules", json=payload)
        new_module_id = resp.get("id")
        if new_module_id is None:
            logger.warning("Canvas did not return a module id for old_id=%s; response=%s", old_module_id, resp)
            # Skip item creation if module create failed
            continue

        id_map["modules"][old_module_id] = new_module_id
        logger.info("Created module '%s' old_id=%s → new_id=%s", m.get("name"), old_module_id, new_module_id)

        # Create items
        items = _sorted_items(m.get("items", []))
        for it in items:
            item_payload, warn = _build_item_payload(it, id_map)
            if warn:
                logger.warning("Skipping item in module old_id=%s: %s; item=%s", old_module_id, warn, it)
                continue

            logger.debug(
                "Adding item to module new_id=%s: payload=%s", new_module_id, item_payload
            )
            canvas.post_json(
                f"/courses/{target_course_id}/modules/{new_module_id}/items",
                json=item_payload,
            )

    logger.info("Modules import complete")

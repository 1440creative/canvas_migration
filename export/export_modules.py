# export/export_modules.py
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, DefaultDict, Optional
import json

from logging_setup import get_logger
from utils.api import CanvasAPI
from utils.fs import ensure_dir, atomic_write, json_dumps_stable


def export_modules(course_id: int, export_root: Path, api: CanvasAPI) -> List[Dict[str, Any]]:
    """
    Export Canvas modules + items with deterministic structure and
    backfill artifact metadata files with module_item_ids.
    """
    log = get_logger(artifact="modules", course_id=course_id)

    course_root = export_root / str(course_id)
    modules_root = course_root / "modules"
    ensure_dir(modules_root)

    # 1) Fetch modules list
    log.info("fetching modules list", extra={"endpoint": f"courses/{course_id}/modules"})
    modules = api.get(f"courses/{course_id}/modules", params={"per_page": 100})
    if not isinstance(modules, list):
        raise TypeError("Expected list of modules from Canvas API")

    # Deterministic sort for modules
    def m_key(m: Dict[str, Any]):
        pos = m.get("position") if m.get("position") is not None else 999_999
        mid = m.get("id") or 0
        return (pos, mid)

    modules_sorted = sorted(modules, key=m_key)

    exported: List[Dict[str, Any]] = []

    # Backrefs: artifact-key -> list[module_item_id]
    page_backrefs: DefaultDict[str, List[int]] = defaultdict(list)        # key: page slug (url)
    assignment_backrefs: DefaultDict[int, List[int]] = defaultdict(list)  # key: assignment id
    file_backrefs: DefaultDict[int, List[int]] = defaultdict(list)        # key: file id
    quiz_backrefs: DefaultDict[int, List[int]] = defaultdict(list)        # key: quiz id
    discussion_backrefs: DefaultDict[int, List[int]] = defaultdict(list)  # key: discussion topic id

    for m_pos, m in enumerate(modules_sorted, start=1):
        module_id = int(m["id"])

        # 2) Fetch items for each module
        log.info("fetching module items", extra={"module_id": module_id})
        items = api.get(f"courses/{course_id}/modules/{module_id}/items", params={"per_page": 100})
        if not isinstance(items, list):
            raise TypeError("Expected list of module items from Canvas API")

        # Deterministic sort for items
        def mi_key(i: Dict[str, Any]):
            pos = i.get("position") if i.get("position") is not None else 999_999
            iid = i.get("id") or 0
            return (pos, iid)

        items_sorted = sorted(items, key=mi_key)

        # 3) Convert to metadata + collect backrefs
        item_metas: List[Dict[str, Any]] = []
        for it in items_sorted:
            item_meta: Dict[str, Any] = {
                "id": it.get("id"),
                "position": it.get("position"),
                "type": it.get("type"),                # "Page", "Assignment", "File", "Quiz", "Discussion"
                "content_id": it.get("content_id"),    # None for Page (Canvas uses page_url)
                "title": it.get("title"),
                "url": it.get("page_url") or it.get("html_url") or None,
            }
            item_metas.append(item_meta)

            # Collect backrefs by type
            item_type = it.get("type")
            item_id = it.get("id")
            content_id = it.get("content_id")

            if item_type == "Page" and it.get("page_url") and item_id:
                page_backrefs[str(it["page_url"]).strip()].append(int(item_id))
            elif item_type == "Assignment" and content_id and item_id:
                assignment_backrefs[int(content_id)].append(int(item_id))
            elif item_type == "File" and content_id and item_id:
                file_backrefs[int(content_id)].append(int(item_id))
            elif item_type == "Quiz" and content_id and item_id:
                quiz_backrefs[int(content_id)].append(int(item_id))
            elif item_type in ("Discussion", "DiscussionTopic") and content_id and item_id:
                discussion_backrefs[int(content_id)].append(int(item_id))

        module_meta: Dict[str, Any] = {
            "id": module_id,
            "name": m.get("name"),
            "position": m_pos,
            "published": bool(m.get("published", True)),
            "items": item_metas,
            "updated_at": m.get("updated_at") or "",
            "source_api_url": api.api_root.rstrip("/") + f"/courses/{course_id}/modules/{module_id}",
        }

        # 4) Write per-module metadata
        mod_dir = modules_root / f"{m_pos:03d}_{module_id}"
        ensure_dir(mod_dir)
        atomic_write(mod_dir / "module_metadata.json", json_dumps_stable(module_meta))
        exported.append(module_meta)

        log.info("exported module", extra={"module_id": module_id, "position": m_pos, "items": len(items_sorted)})

    # 5) Backfill artifact metadata files with collected module_item_ids
    pages_updated = _backfill_by_slug(
        course_root, "pages", "page_metadata.json", "url", page_backrefs
    )
    assignments_updated = _backfill_by_id(
        course_root, "assignments", "assignment_metadata.json", "id", assignment_backrefs
    )
    #Files use sidecars like: files/.../filename.ext.metadata.json
    files_updated = _backfill_file_sidecars_by_id(course_root, file_backrefs)

    quizzes_updated = _backfill_by_id(
        course_root, "quizzes", "quiz_metadata.json", "id", quiz_backrefs
    )
    discussions_updated = _backfill_by_id(
        course_root, "discussions", "discussion_metadata.json", "id", discussion_backrefs
    )

    log.info(
        "backfill complete",
        extra={
            "pages": pages_updated,
            "assignments": assignments_updated,
            "files": files_updated,
            "quizzes": quizzes_updated,
            "discussions": discussions_updated,
        },
    )
    
    # NEW: write combined modules.json for the importer/dry-run
    atomic_write(modules_root / "modules.json", json_dumps_stable(exported))

    log.info("exported modules complete", extra={"count": len(exported)})
    return exported


# ----------------------- helpers -----------------------

def _merge_ids(existing: Optional[List[int]], new_ids: List[int]) -> List[int]:
    base = set(existing or [])
    base.update(new_ids)
    return sorted(base)


def _backfill_json_list(meta_path: Path, new_ids: List[int]) -> bool:
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    before = data.get("module_item_ids", [])
    after = _merge_ids(before, new_ids)
    if after != before:
        data["module_item_ids"] = after
        atomic_write(meta_path, json_dumps_stable(data))
        return True
    return False


def _backfill_by_slug(
    course_root: Path,
    artifact_dir: str,
    meta_filename: str,
    slug_key: str,
    slug_to_ids: Dict[str, List[int]],
) -> int:
    """Match by slug string in metadata (e.g., PageMeta.url)."""
    root = course_root / artifact_dir
    if not root.exists():
        return 0

    updated = 0
    for meta_path in sorted(root.glob(f"*/{meta_filename}")):
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        slug = str(data.get(slug_key, "")).strip()
        if not slug:
            continue
        ids = slug_to_ids.get(slug)
        if ids and _backfill_json_list(meta_path, ids):
            updated += 1
    return updated


def _backfill_by_id(
    course_root: Path,
    artifact_dir: str,
    meta_filename: str,
    id_key: str,
    id_to_ids: Dict[int, List[int]],
) -> int:
    """Match by numeric id in metadata (e.g., AssignmentMeta.id)."""
    root = course_root / artifact_dir
    if not root.exists():
        return 0

    updated = 0
    for meta_path in sorted(root.glob(f"*/{meta_filename}")):
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        obj_id = data.get(id_key)
        if not isinstance(obj_id, int):
            continue
        ids = id_to_ids.get(obj_id)
        if ids and _backfill_json_list(meta_path, ids):
            updated += 1
    return updated

def _backfill_file_sidecars_by_id(
    course_root: Path,
    id_to_ids: Dict[int, List[int]],
) -> int:
    """
    Match Canvas File ids to *.metadata.json sidecars and merge module_item_ids.
    """
    root = course_root / "files"
    if not root.exists():
        return 0

    updated = 0
    for sidecar in sorted(root.glob("**/*.metadata.json")):
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        fid = data.get("id")
        if not isinstance(fid, int):
            continue
        ids = id_to_ids.get(fid)
        if not ids:
            continue
        before = data.get("module_item_ids", [])
        after = _merge_ids(before, ids)
        if after != before:
            data["module_item_ids"] = after
            atomic_write(sidecar, json_dumps_stable(data))
            updated += 1
    return updated

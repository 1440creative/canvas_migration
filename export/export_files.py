# export/export_files.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
import os
import tempfile

from logging_setup import get_logger
from utils.api import CanvasAPI
from utils.fs import ensure_dir, json_dumps_stable, safe_relpath, file_hashes
from utils.strings import sanitize_slug


CHUNK = 1024 * 1024  # 1 MiB
FALLBACK_FOLDER = "unfiled"


def export_files(course_id: int, export_root: Path, api: CanvasAPI) -> List[Dict[str, Any]]:
    """
    Export Canvas course files with deterministic, portable layout.

    Layout (mirrors Canvas folders, sanitized):
      export/data/{course_id}/files/<sanitized/folder/path>/filename.ext
                                               └─ filename.ext.metadata.json  (sidecar)

    Notes:
      - We mirror Canvas 'full_name' for folders (minus leading 'Course Files/')
      - Sidecar JSON includes id, content_type, hashes (sha256, md5), folder_path (Canvas full_name),
        file_path (relative POSIX path), and module_item_ids (backfilled later).
      - We stream downloads to avoid large memory usage.
    """
    log = get_logger(artifact="files", course_id=course_id)

    course_root = export_root / str(course_id)
    files_root = course_root / "files"
    ensure_dir(files_root)

    # 1) Build a folder_id -> sanitized path segments map
    folders_map = _fetch_folders_map(course_id, api, log)

    # 2) List files
    log.info("fetching files list", extra={"endpoint": f"courses/{course_id}/files"})
    items = api.get(f"courses/{course_id}/files", params={"per_page": 100})
    if not isinstance(items, list):
        raise TypeError("Expected list of files from Canvas API")

    # Deterministic sort: by folder path (string), then filename, then id
    def sort_key(f: Dict[str, Any]):
        folder_id = f.get("folder_id")
        folder_key = _folder_key_string(folders_map.get(int(folder_id)) if isinstance(folder_id, int) else None)
        filename = (f.get("filename") or "").strip()
        fid = f.get("id") or 0
        return (folder_key, filename, fid)

    items_sorted = sorted(items, key=sort_key)

    exported: List[Dict[str, Any]] = []

    for f in items_sorted:
        fid = int(f["id"])
        filename = f.get("filename") or f"file-{fid}"
        content_type = f.get("content-type") or f.get("content_type")  # Canvas uses 'content-type'
        folder_id = f.get("folder_id")

        # Resolve sanitized folder path segments
        segs = folders_map.get(int(folder_id)) if isinstance(folder_id, int) else None
        if not segs:
            segs = [FALLBACK_FOLDER]

        file_dir = files_root.joinpath(*segs)
        ensure_dir(file_dir)

        file_path = file_dir / filename  # keep original filename on disk
        rel_file_path = safe_relpath(file_path, course_root)

        # Download via Canvas file 'url' (requires auth header)
        # If 'url' missing, try 'download_url' or 'href'
        download_url = f.get("url") or f.get("download_url") or f.get("href")
        if not download_url:
            # Fallback: Canvas file detail is under /files/{id}; that returns a JSON with 'url'
            detail = api.get(f"files/{fid}")
            if isinstance(detail, dict):
                download_url = detail.get("url") or detail.get("download_url")

        if not download_url:
            log.info("skipping file without download url", extra={"file_id": fid, "filename": filename})
            # Still write metadata without hashes so you can see it missed
            meta = _build_metadata(
                fid=fid,
                filename=filename,
                content_type=content_type,
                rel_file_path=rel_file_path,
                folder_full_name=_folder_full_name(folders_map, folder_id),
                sha256=None,
                md5=None,
                course_root=course_root,
                course_id=course_id,
                api=api,
            )
            _write_sidecar(file_path, meta)
            exported.append(meta)
            continue

        # Stream the download to a temp file in the destination dir, then atomic replace
        _download_stream_to_path(api, download_url, file_path)

        # Compute hashes
        hashes = file_hashes(file_path)

        # Build metadata
        meta = _build_metadata(
            fid=fid,
            filename=filename,
            content_type=content_type,
            rel_file_path=rel_file_path,
            folder_full_name=_folder_full_name(folders_map, folder_id),
            sha256=hashes["sha256"],
            md5=hashes["md5"],
            course_root=course_root,
            course_id=course_id,
            api=api,
        )

        _write_sidecar(file_path, meta)
        exported.append(meta)

        log.info(
            "exported file",
            extra={"file_id": fid, "folder": "/".join(segs), "filename": filename, "path": rel_file_path},
        )

    log.info("exported files complete", extra={"count": len(exported)})
    return exported


# --------------------- helpers ---------------------

def _fetch_folders_map(course_id: int, api: CanvasAPI, log) -> Dict[int, List[str]]:
    """
    Return a map of folder_id -> list of sanitized path segments (relative under files/).
    We remove the leading 'Course Files' segment (Canvas convention) and sanitize each segment.
    """
    log.info("fetching folders", extra={"endpoint": f"courses/{course_id}/folders"})
    folders = api.get(f"courses/{course_id}/folders", params={"per_page": 100})
    mapping: Dict[int, List[str]] = {}
    if isinstance(folders, list):
        for fd in folders:
            fid = fd.get("id")
            full_name = fd.get("full_name") or ""
            if isinstance(fid, int) and full_name:
                segs = _sanitize_folder_full_name(full_name)
                mapping[fid] = segs if segs else [FALLBACK_FOLDER]
    return mapping


def _sanitize_folder_full_name(full_name: str) -> List[str]:
    """
    Canvas 'full_name' examples:
      'course files'                        -> []
      'course files/Unit 1'                 -> ['unit-1']
      'course files/Unit 1/Images & PDFs'   -> ['unit-1', 'images-pdfs']
    We drop the leading 'course files' (case-insensitive) and sanitize each remaining segment.
    """
    parts = [p for p in full_name.split("/") if p != ""]
    if parts and parts[0].strip().lower() == "course files":
        parts = parts[1:]
    return [sanitize_slug(p) for p in parts if p.strip()]


def _folder_key_string(segs: Optional[List[str]]) -> str:
    return "/".join(segs or [FALLBACK_FOLDER])


def _folder_full_name(folders_map: Dict[int, List[str]] | None, folder_id: Any) -> str:
    """Return a best-effort original-ish folder string for metadata (not sanitized)."""
    # We don't have originals here unless we pass them through; record a normalized display path instead.
    if isinstance(folder_id, int) and folders_map and folder_id in folders_map:
        return "/".join(folders_map[folder_id])
    return FALLBACK_FOLDER


def _download_stream_to_path(api: CanvasAPI, url: str, dest: Path) -> None:
    """Stream a download to dest atomically (tmp file + replace)."""
    ensure_dir(dest.parent)
    with tempfile.NamedTemporaryFile(delete=False, dir=dest.parent) as tmp:
        tmp_path = Path(tmp.name)
    try:
        with api.session.get(url, stream=True, timeout=(5, 60)) as r:  # type: ignore[attr-defined]
            r.raise_for_status()
            with open(tmp_path, "wb") as out:
                for chunk in r.iter_content(CHUNK):
                    if chunk:
                        out.write(chunk)
        os.replace(tmp_path, dest)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def _build_metadata(
    *,
    fid: int,
    filename: str,
    content_type: Optional[str],
    rel_file_path: str,
    folder_full_name: str,
    sha256: Optional[str],
    md5: Optional[str],
    course_root: Path,
    course_id: int,
    api: CanvasAPI,
) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "id": fid,
        "filename": filename,
        "content_type": content_type,
        "sha256": sha256,
        "md5": md5,
        "folder_path": folder_full_name,          # normalized display path
        "file_path": rel_file_path,               # POSIX-relative path from course root
        "module_item_ids": [],                    # backfilled by modules
        "updated_at": None,                       # could be set if Canvas includes updated_at on files
        "source_api_url": api.api_root.rstrip("/") + f"/files/{fid}",
    }
    return meta


def _write_sidecar(file_path: Path, meta: Dict[str, Any]) -> None:
    sidecar = file_path.parent / f"{file_path.name}.metadata.json"
    from utils.fs import atomic_write  # avoid circular imports at module import time
    atomic_write(sidecar, json_dumps_stable(meta))

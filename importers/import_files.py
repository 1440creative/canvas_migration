# importers/import_files.py
"""
Import files into a Canvas course with deterministic folder placement and id mapping.

Deterministic folder path:
  {target_course_id}/files[/<subdirs from export_root/files>]

Per file:
  1) Initialize upload via Canvas (begin_course_file_upload)
  2) Perform either S3 multipart POST or InstFS multipart (based on upload_url/params)
  3) Follow finalize redirect if present
  4) Record id_map["files"][old_id] = new_id
  5) Store sha256 + new_id in a manifest so identical reruns are skipped
"""

from __future__ import annotations

import json
import mimetypes
import time
from pathlib import Path
from typing import Dict, Any, Optional, Protocol

import requests
from logging_setup import get_logger
from utils.api import DEFAULT_TIMEOUT
from utils.fs import file_hashes  # used for manifest-based skip

__all__ = ["import_files", "_manifest_path"]

# ---------------- Manifest helpers (kept tiny; tests import _manifest_path) -----

_MANIFEST_NAME = ".uploads_manifest.json"

def _manifest_path(export_root: Path) -> Path:
    """Path to uploads manifest under the export root."""
    return export_root / _MANIFEST_NAME

def _load_manifest(export_root: Path) -> dict:
    p = _manifest_path(export_root)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def _save_manifest(export_root: Path, manifest: dict) -> None:
    try:
        _manifest_path(export_root).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except Exception:
        # best-effort; do not fail the import if manifest can't be saved
        pass

# ---------------- Protocol (compatible with DummyCanvas in tests) ---------------

class CanvasLike(Protocol):
    session: requests.Session
    api_root: str

    def begin_course_file_upload(
        self,
        course_id: int,
        *,
        name: str,
        parent_folder_path: str,
        on_duplicate: str = "overwrite",
    ) -> Dict[str, Any]: ...
    def _multipart_post(self, url: str, *, data: Dict[str, Any], files: Dict[str, Any]) -> requests.Response: ...

# ---------------- Helpers -------------------------------------------------------

def _coerce_int(x: Any) -> Optional[int]:
    try:
        return int(x) if x is not None else None
    except Exception:
        return None

def _safe_json(resp: requests.Response) -> dict:
    if resp.status_code == 204 or not resp.content:
        return {}
    try:
        return resp.json()
    except ValueError:
        return {}

def _extract_new_file_id(payload: Any) -> Optional[int]:
    """
    Try to find the new file id in common Canvas shapes:
      { "id": 123 } or { "attachment": { "id": 123, ... } }
    """
    if not isinstance(payload, dict):
        return None
    if "id" in payload:
        try:
            return int(payload["id"])
        except Exception:
            pass
    att = payload.get("attachment")
    if isinstance(att, dict) and "id" in att:
        try:
            return int(att["id"])
        except Exception:
            pass
    return None

def _looks_like_instfs(upload_url: str, params: dict) -> bool:
    host_hint = "inscloudgate.net" in str(upload_url) or "inst-fs" in str(upload_url)
    if not host_hint:
        return False
    keys = set((params or {}).keys())
    if not keys:
        return True
    jsonish = {"filename", "content_type", "size", "name"}
    s3ish = {
        "policy", "signature", "AWSAccessKeyId", "key",
        "x-amz-signature", "x-amz-credential", "x-amz-algorithm",
        "success_action_status",
    }
    return keys.issubset(jsonish) and not (keys & s3ish)

# ---------------- Core upload ---------------------------------------------------

def _upload_one(
    *,
    canvas: CanvasLike,
    course_id: int,
    file_path: Path,
    folder_path: str,
    on_duplicate: str,
    logger,
) -> int:
    """
    Upload a single file via Canvas multi-step flow.
    """
    init = canvas.begin_course_file_upload(
        course_id=course_id,
        name=file_path.name,
        parent_folder_path=folder_path,
        on_duplicate=on_duplicate,
    )
    try:
        size_bytes = file_path.stat().st_size
    except Exception:
        size_bytes = -1
    logger.debug(
        "begin file upload: %s (size=%s bytes) -> %s",
        file_path,
        size_bytes,
        folder_path or "/",
    )
    upload_url = init["upload_url"]
    params = init.get("upload_params", {}) or {}

    # Branch: InstFS vs S3 multipart
    if _looks_like_instfs(str(upload_url), params):
        fname = params.get("filename") or params.get("name") or file_path.name
        ctype = params.get("content_type") or (mimetypes.guess_type(file_path.name)[0] or "application/octet-stream")
        try:
            size_val = int(params["size"]) if "size" in params else file_path.stat().st_size
        except Exception:
            size_val = file_path.stat().st_size

        start = time.time()
        with open(file_path, "rb") as fh:
            up = canvas._multipart_post(
                str(upload_url),
                data={"filename": fname, "content_type": ctype, "size": int(size_val)},
                files={"file": (fname, fh, ctype)},
            )
        logger.debug(
            "upload complete: %s status=%s duration=%.2fs",
            file_path,
            up.status_code,
            time.time() - start,
        )

        if 300 <= up.status_code < 400 and "Location" in up.headers:
            finalize = canvas.session.get(up.headers["Location"], timeout=DEFAULT_TIMEOUT)
            finalize.raise_for_status()
            payload = _safe_json(finalize)
        else:
            up.raise_for_status()
            payload = _safe_json(up)

        new_id = _extract_new_file_id(payload)
        if new_id is None:
            raise RuntimeError("Canvas upload did not return a file id (InstFS)")
        return new_id

    # S3-style multipart
    start = time.time()
    with open(file_path, "rb") as fh:
        up = canvas._multipart_post(str(upload_url), data=params, files={"file": (file_path.name, fh)})
    logger.debug(
        "upload complete: %s status=%s duration=%.2fs",
        file_path,
        up.status_code,
        time.time() - start,
    )

    if 300 <= up.status_code < 400 and "Location" in up.headers:
        finalize = canvas.session.get(up.headers["Location"], timeout=DEFAULT_TIMEOUT)
        finalize.raise_for_status()
        payload = _safe_json(finalize)
    else:
        up.raise_for_status()
        payload = _safe_json(up)

    new_id = _extract_new_file_id(payload)
    if new_id is None:
        raise RuntimeError("Canvas upload did not return a file id (S3)")
    return new_id

# ---------------- Public entrypoint --------------------------------------------

def import_files(
    *,
    target_course_id: int,
    export_root: Path,
    canvas: CanvasLike,
    id_map: Dict[str, Dict[int, int]],
    on_duplicate: str = "overwrite",  # or "rename"
) -> Dict[str, int]:
    """
    Upload all files under export_root/files with deterministic folder placement:
      mirrors the exported folder hierarchy (relative to the files/ directory).

    Updates id_map["files"][old_id] = new_id.
    Returns counters: {"imported": N, "skipped": K, "failed": M, "total": T}
    """
    logger = get_logger(artifact="files", course_id=target_course_id)

    files_dir = export_root / "files"
    if not files_dir.exists():
        logger.info("No files directory found at %s", files_dir)
        return {"imported": 0, "skipped": 0, "failed": 0, "total": 0}

    id_map.setdefault("files", {})
    imported = skipped = failed = 0

    # Load/save manifest
    manifest = _load_manifest(export_root)

    for meta_file in files_dir.rglob("*.metadata.json"):
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception as e:
            failed += 1
            logger.exception("Failed to read metadata %s: %s", meta_file, e)
            continue

        old_id = _coerce_int(meta.get("id"))
        filename = meta.get("file_name") or meta.get("filename")
        if old_id is None or not filename:
            skipped += 1
            logger.warning("Skipping %s (missing id or file_name)", meta_file)
            continue

        file_path = meta_file.parent / filename
        if not file_path.exists():
            failed += 1
            logger.error("Exported file missing for metadata %s (expected %s)", meta_file, file_path)
            continue

        # Compute sha256 for manifest-based skip
        try:
            local_sha = file_hashes(file_path)["sha256"]
        except Exception:
            local_sha = None

        rel_path = file_path.relative_to(files_dir)
        rel = rel_path.as_posix()
        manifest_key = rel

        # Skip if manifest has same sha256; also restore mapping for id_map
        if local_sha:
            prev = manifest.get(manifest_key)
            if isinstance(prev, dict) and prev.get("sha256") == local_sha:
                prev_course_id = _coerce_int(prev.get("target_course_id"))
                prev_new_id = _coerce_int(prev.get("new_id"))
                if prev_course_id == target_course_id and prev_new_id is not None:
                    id_map["files"][old_id] = prev_new_id
                    skipped += 1
                    logger.info("Skipped upload (same sha256): %s → existing_id=%s", rel, prev_new_id)
                    continue

        # Preserve exported folder hierarchy relative to files/
        subdir_path = rel_path.parent
        if str(subdir_path) in ("", "."):
            folder_path = ""  # Canvas treats empty string as the course root
        else:
            folder_path = subdir_path.as_posix()

        logger.debug("Uploading: rel=%s → folder=%s", rel, folder_path)

        try:
            new_id = _upload_one(
                canvas=canvas,
                course_id=target_course_id,
                file_path=file_path,
                folder_path=folder_path,
                on_duplicate=on_duplicate,
                logger=logger,
            )
            id_map["files"][old_id] = int(new_id)
            imported += 1
            logger.info("Uploaded %s → new_id=%s (mapped from old_id=%s)", rel, new_id, old_id)

            # Update manifest with sha + id for future skips
            if local_sha:
                manifest[manifest_key] = {
                    "sha256": local_sha,
                    "new_id": int(new_id),
                    "target_course_id": target_course_id,
                }

        except Exception as e:
            failed += 1
            logger.exception("Failed to upload %s: %s", rel, e)

    _save_manifest(export_root, manifest)

    total = imported + skipped + failed
    logger.info("File import complete. imported=%d skipped=%d failed=%d total=%d",
                imported, skipped, failed, total)
    return {"imported": imported, "skipped": skipped, "failed": failed, "total": total}

# importers/import_files.py
"""
Import files into a Canvas course using your CanvasAPI-style wrapper.

Reads exported file metadata (.metadata.json next to each file) under:
    export_root/files/**/<filename> and <filename>.metadata.json

Per file:
  1) Initialize upload via API (returns upload_url + upload_params)
  2) Perform either:
       - S3-style multipart POST (classic)
       - InstFS JSON handshake then PUT (inscloudgate/inst-fs hosts)
  3) Follow finalize redirect (if present) using the same auth session
  4) Record old_id -> new_id in id_map["files"]

Public entrypoint: `import_files`.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Any, Protocol, Optional

import requests
from logging_setup import get_logger  # project-level logger adapter
from utils.fs import file_hashes

__all__ = ["import_files", "_manifest_path"]

# ---- Manifest helpers -------------------------------------------------------
_MANIFEST_NAME = ".uploads_manifest.json"


def _manifest_path(export_root: Path) -> Path:
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
    _manifest_path(export_root).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


# ---- Protocol to decouple from your exact CanvasAPI class -------------------
class CanvasLike(Protocol):
    session: requests.Session
    api_root: str

    def post(self, endpoint: str, **kwargs) -> requests.Response: ...
    def post_json(self, endpoint: str, *, payload: Dict[str, Any]) -> Dict[str, Any]: ...
    def begin_course_file_upload(
        self,
        course_id: int,
        *,
        name: str,
        parent_folder_path: str,
        on_duplicate: str = "overwrite",
    ) -> Dict[str, Any]: ...
    def _multipart_post(self, url: str, *, data: Dict[str, Any], files: Dict[str, Any]) -> requests.Response: ...


# ---- Helpers ----------------------------------------------------------------
def _safe_relpath(path: Path, root: Path) -> str:
    """Return POSIX-style relative path (deterministic across OS)."""
    return path.relative_to(root).as_posix()


def _coerce_int(val: Any) -> Optional[int]:
    try:
        return int(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _extract_new_file_id(payload: Any) -> Optional[int]:
    """
    Try to pull a file id out of various Canvas upload response shapes.
    Accepts ints or numeric strings, and nested 'attachment' objects.
    """
    if not isinstance(payload, dict):
        return None

    if "id" in payload:
        try:
            return int(payload["id"])
        except (TypeError, ValueError):
            pass

    att = payload.get("attachment")
    if isinstance(att, dict) and "id" in att:
        try:
            return int(att["id"])
        except (TypeError, ValueError):
            pass

    return None


def _safe_json(resp: requests.Response) -> dict:
    """Best-effort JSON parse (handles empty/204/non-JSON)."""
    if resp.status_code == 204 or not resp.content:
        return {}
    try:
        return resp.json()
    except ValueError:
        return {}


def _looks_like_instfs(upload_url: str, params: dict) -> bool:
    """
    Heuristic: InstFS handshake when upload host is inscloudgate/inst-fs and
    upload_params look like {"filename","content_type","size"} (no S3 fields).
    """
    host_hint = "inscloudgate.net" in str(upload_url) or "inst-fs" in str(upload_url)
    keys = set((params or {}).keys())
    jsonish = {"filename", "content_type", "size"}
    s3ish = {
        "policy",
        "signature",
        "AWSAccessKeyId",
        "key",
        "x-amz-signature",
        "x-amz-credential",
        "x-amz-algorithm",
        "success_action_status",
    }
    return host_hint and keys.issubset(jsonish) and not (keys & s3ish)


# ---- Public entrypoint ------------------------------------------------------
def import_files(
    *,
    target_course_id: int,
    export_root: Path,
    canvas: CanvasLike,
    id_map: Dict[str, Dict[int, int]],
    on_duplicate: str = "overwrite",  # or "rename"
    verbosity: int = 1,  # kept for CLI compatibility; logging level configured elsewhere
) -> None:
    """
    Upload files from export_root/files into the Canvas course and update id_map["files"].
    """
    logger = get_logger(course_id=target_course_id, artifact="files")

    files_dir = export_root / "files"
    if not files_dir.exists():
        logger.warning("No files directory found at %s", files_dir)
        return

    logger.info("Starting file import from %s", files_dir)

    file_map = id_map.setdefault("files", {})
    imported = 0
    skipped = 0
    failed = 0

    # Load uploads manifest once for the whole run
    manifest: dict = _load_manifest(export_root)

    # Find all sidecar metadata files produced by your exporter
    for meta_file in files_dir.rglob("*.metadata.json"):
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        except Exception as e:
            failed += 1
            logger.exception("Failed to read metadata %s: %s", meta_file, e)
            continue

        old_id = _coerce_int(metadata.get("id"))
        file_name = metadata.get("file_name") or metadata.get("filename")
        if old_id is None or not file_name:
            skipped += 1
            logger.warning("Skipping %s (missing id or file_name)", meta_file)
            continue

        exported_file = meta_file.parent / file_name
        if not exported_file.exists():
            failed += 1
            logger.error(
                "Exported file missing for metadata %s (expected %s)",
                meta_file,
                exported_file,
            )
            continue

        rel_path = _safe_relpath(exported_file, files_dir)

        # Prefer explicit folder_path from metadata; otherwise derive from layout
        folder_path = metadata.get("folder_path")
        if not folder_path:
            parent_rel = Path(rel_path).parent.as_posix()
            folder_path = parent_rel if parent_rel not in ("", ".") else "/"

        # --- Check manifest for same blob (sha256) and skip if identical ---
        try:
            local_sha = file_hashes(exported_file)["sha256"]
        except Exception as e:
            local_sha = None
            logger.debug("Could not compute sha256 for %s: %s", rel_path, e)

        manifest_key = rel_path  # 'subdir/name.ext'
        if local_sha:
            prev = manifest.get(manifest_key)
            if prev and isinstance(prev, dict) and prev.get("sha256") == local_sha:
                new_id_prev = prev.get("new_id")
                if old_id is not None and isinstance(new_id_prev, int):
                    file_map[old_id] = new_id_prev
                skipped += 1
                logger.info(
                    "Skipped upload (same sha256): %s → existing_id=%s",
                    rel_path,
                    new_id_prev,
                )
                continue

        logger.debug(
            "Processing file: rel=%s old_id=%s folder=%s size=%s bytes",
            rel_path,
            old_id,
            folder_path,
            exported_file.stat().st_size,
        )

        try:
            new_id = _upload_file_via_canvas_api(
                canvas=canvas,
                course_id=target_course_id,
                file_path=exported_file,
                folder_path=folder_path,
                on_duplicate=on_duplicate,
                logger=logger,
            )
            file_map[old_id] = int(new_id)
            imported += 1
            logger.info("Uploaded %s → new_id=%s", rel_path, new_id)

            # Update manifest with the new sha and id
            if local_sha:
                manifest[manifest_key] = {"sha256": local_sha, "new_id": int(new_id)}

        except Exception as e:
            failed += 1
            logger.exception("Failed to upload %s: %s", rel_path, e)

    # Persist manifest at the end (best-effort)
    try:
        _save_manifest(export_root, manifest)
    except Exception as e:
        logger.warning("Could not save uploads manifest: %s", e)

    logger.info(
        "File import complete. imported=%d skipped=%d failed=%d total=%d",
        imported,
        skipped,
        failed,
        imported + skipped + failed,
    )


# ---- Core upload routine ----------------------------------------------------
def _upload_file_via_canvas_api(
    *,
    canvas: CanvasLike,
    course_id: int,
    file_path: Path,
    folder_path: str,
    on_duplicate: str,
    logger: logging.Logger,
) -> int:
    """
    Upload one file using Canvas' multi-step flow with your CanvasAPI wrapper.

    Supports:
      - S3-style multipart form POST (classic)
      - InstFS JSON handshake → PUT raw bytes (inscloudgate/inst-fs)

    Returns:
        New Canvas file ID (int).
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Missing exported file: {file_path}")

    # Step 1: Initialize upload via API
    init_json = canvas.begin_course_file_upload(
        course_id=course_id,
        name=file_path.name,
        parent_folder_path=folder_path,
        on_duplicate=on_duplicate,
    )

    upload_url = init_json["upload_url"]
    upload_params = init_json.get("upload_params", {}) or {}
    method_hint = (init_json.get("http_method") or init_json.get("method") or "POST").upper()

    # ---- Case A: InstFS JSON-handshake flow --------------------------------
    if _looks_like_instfs(upload_url, upload_params):
        logger.debug(
            "InstFS JSON handshake detected url=%s params_keys=%s",
            upload_url,
            sorted(upload_params.keys()),
        )

        # 2a) JSON handshake (no file yet)
        h = canvas.session.post(upload_url, json=upload_params, timeout=(5, 60))
        h.raise_for_status()
        hj = _safe_json(h)

        next_method = (hj.get("http_method") or hj.get("method") or "PUT").upper()
        next_url = hj.get("upload_url") or hj.get("location") or h.headers.get("Location")
        next_headers = hj.get("headers") or {}

        # Some deployments may return the final attachment right away
        if not next_url:
            new_id = _extract_new_file_id(hj)
            if new_id is not None:
                return new_id
            logger.debug("Unexpected InstFS handshake response: %s", hj)
            raise RuntimeError("InstFS handshake did not provide next upload URL")

        # 2b) Send the bytes according to server instruction
        if next_method == "PUT":
            # PUT raw bytes; set Content-Type from provided hints
            ct = (
                upload_params.get("content_type")
                or next_headers.get("Content-Type")
                or "application/octet-stream"
            )
            hdrs = canvas.session.headers.copy()
            # keep auth header; merge additional headers (sans content-type to avoid duplicates)
            for k, v in next_headers.items():
                if k.lower() != "content-type":
                    hdrs[k] = v
            hdrs["Content-Type"] = ct

            with open(file_path, "rb") as fh:
                put = canvas.session.put(next_url, data=fh, headers=hdrs, timeout=(5, 60))

            # Finalize / parse
            if 300 <= put.status_code < 400 and "Location" in put.headers:
                fin = canvas.session.get(put.headers["Location"], timeout=(5, 60))
                fin.raise_for_status()
                payload = _safe_json(fin)
            else:
                put.raise_for_status()
                payload = _safe_json(put)

        else:
            # Fallback: server asks for another POST (sometimes with upload_params + file)
            with open(file_path, "rb") as fh:
                post2 = canvas.session.post(
                    next_url,
                    data=hj.get("upload_params") or {},
                    files={"file": (file_path.name, fh)},
                    headers={k: v for k, v in next_headers.items() if k.lower() != "content-type"},
                    timeout=(5, 60),
                )

            if 300 <= post2.status_code < 400 and "Location" in post2.headers:
                fin = canvas.session.get(post2.headers["Location"], timeout=(5, 60))
                fin.raise_for_status()
                payload = _safe_json(fin)
            else:
                post2.raise_for_status()
                payload = _safe_json(post2)

        new_id = _extract_new_file_id(payload)
        if new_id is not None:
            return new_id

        logger.debug("Unexpected upload response payload (InstFS): %s", payload)
        raise RuntimeError("InstFS upload did not return a file id")

    # ---- Case B: S3-style multipart POST (classic) --------------------------
    # Some initializers include method=POST and S3 fields (policy/signature/etc.)
    logger.debug(
        "S3-style multipart flow url=%s params_keys=%s method_hint=%s",
        upload_url,
        sorted(upload_params.keys()),
        method_hint,
    )

    with open(file_path, "rb") as fh:
        up = canvas._multipart_post(
            str(upload_url),
            data=upload_params,
            files={"file": (file_path.name, fh)},
        )

    # Finalize or parse direct response
    if 300 <= up.status_code < 400 and "Location" in up.headers:
        finalize_url = up.headers["Location"]
        finalize = canvas.session.get(finalize_url, timeout=(5, 60))
        finalize.raise_for_status()
        payload: Any = _safe_json(finalize)
    else:
        up.raise_for_status()
        payload = _safe_json(up)

    new_id = _extract_new_file_id(payload)
    if new_id is not None:
        return new_id

    logger.debug("Unexpected upload response payload (S3/multipart): %s", payload)
    raise RuntimeError("Canvas upload did not return a file id")

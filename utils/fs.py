# utils/fs.py

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def ensure_dir(path: Path) -> None:
    """Create directory (and parents) if missing."""
    path.mkdir(parents=True, exist_ok=True)


def atomic_write(path: Path, data: str | bytes) -> None:
    """
    Write to a temp file in the same dir then atomic-rename.
    Prevents partial files if the process dies mid-write.
    """
    ensure_dir(path.parent)
    mode = "wb" if isinstance(data, (bytes, bytearray)) else "w"
    # create tmp in same directory so os.replace is atomic on the filesystem
    with tempfile.NamedTemporaryFile(delete=False, dir=path.parent) as tmp:
        tmp_path = Path(tmp.name)
    try:
        with open(tmp_path, mode, encoding=None if "b" in mode else "utf-8") as f:
            f.write(data)  # type: ignore[arg-type]
        os.replace(tmp_path, path)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
        except Exception:
            # best-effort cleanup
            pass


def json_dumps_stable(obj: Any) -> str:
    """Deterministic JSON: 2-space indent, sorted keys, UTF-8, trailing newline."""
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def safe_relpath(path: Path, start: Path) -> str:
    """Return a POSIX-style relative path (forward slashes) for portability."""
    rel = Path(os.path.relpath(path, start))
    return rel.as_posix()


def file_hashes(path: Path, chunk_size: int = 1024 * 1024) -> dict[str, str]:
    """Compute sha256 and md5 for a file (streamed)."""
    sha256 = hashlib.sha256()
    md5 = hashlib.md5()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            sha256.update(chunk)
            md5.update(chunk)
    return {"sha256": sha256.hexdigest(), "md5": md5.hexdigest()}

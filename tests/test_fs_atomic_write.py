# tests/test_fs_atomic_write.py
from __future__ import annotations

import os
from pathlib import Path

from utils.fs import atomic_write, ensure_dir


def test_atomic_write_text_and_bytes(tmp_path: Path):
    # Text
    p_txt = tmp_path / "out.txt"
    atomic_write(p_txt, "hello 🌊")
    assert p_txt.read_text(encoding="utf-8") == "hello 🌊"

    # Bytes
    p_bin = tmp_path / "out.bin"
    payload = b"\x00\x01\x02\xff"
    atomic_write(p_bin, payload)
    assert p_bin.read_bytes() == payload


def test_atomic_write_creates_parent_dirs(tmp_path: Path):
    nested = tmp_path / "a" / "b" / "c" / "note.md"
    atomic_write(nested, "# hi\n")
    assert nested.exists()
    assert nested.read_text(encoding="utf-8") == "# hi\n"


def test_atomic_write_is_atomic_replace(tmp_path: Path):
    p = tmp_path / "data.json"

    # First write
    atomic_write(p, '{"v":1}')
    before = p.stat()
    assert p.read_text(encoding="utf-8") == '{"v":1}'

    # Second write (should replace, not append)
    atomic_write(p, '{"v":2}')
    after = p.stat()
    assert p.read_text(encoding="utf-8") == '{"v":2}'

    # On POSIX filesystems, os.replace results in a new inode
    # Don't fail on platforms that don’t expose inode semantics.
    if hasattr(before, "st_ino") and hasattr(after, "st_ino"):
        assert before.st_ino != after.st_ino


def test_atomic_write_no_temp_leftovers(tmp_path: Path):
    # Use a dedicated dir to make assertions easy
    d = tmp_path / "isolated"
    ensure_dir(d)
    target = d / "only.txt"

    atomic_write(target, "one")
    atomic_write(target, "two")  # multiple writes

    # Directory should only contain the target file; no tmp files left behind
    entries = [p.name for p in d.iterdir()]
    assert entries == ["only.txt"], f"leftover files: {entries}"

# tests/test_fs_helpers.py
import json
from pathlib import Path
from utils.fs import json_dumps_stable, safe_relpath, file_hashes


def test_json_dumps_stable_deterministic(tmp_path):
    data = {"b": 1, "a": 2}
    dumped1 = json_dumps_stable(data)
    dumped2 = json_dumps_stable(data)

    # Should always be identical (sorted keys, indent, trailing newline)
    assert dumped1 == dumped2
    assert dumped1.endswith("\n")
    # Parse back and match
    parsed = json.loads(dumped1)
    assert parsed == {"a": 2, "b": 1}


def test_safe_relpath_portable(tmp_path):
    root = tmp_path
    f = root / "subdir" / "file.txt"
    f.parent.mkdir()
    f.write_text("x")

    rel = safe_relpath(f, root)
    assert rel == "subdir/file.txt"  # POSIX-style (forward slashes only)
    assert not rel.startswith("/")   # relative, not absolute


def test_file_hashes_known_values(tmp_path):
    f = tmp_path / "sample.txt"
    f.write_text("hello world\n", encoding="utf-8")

    hashes = file_hashes(f)
    # Known values for "hello world\n"
    assert hashes["sha256"] == "a948904f2f0f479b8f8197694b30184b0d2ed1c1cd2a1ec0fb85d299a192a447"
    assert hashes["md5"] == "6f5902ac237024bdd0c176cb93063dc4"

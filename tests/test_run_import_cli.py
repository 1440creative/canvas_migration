from __future__ import annotations

import pytest

from scripts.run_import import main


def test_dry_run_without_target_id(tmp_path, capsys):
    export_root = tmp_path / "export" / "data" / "101"
    export_root.mkdir(parents=True, exist_ok=True)

    rc = main(["--export-root", str(export_root), "--dry-run"])

    assert rc == 0
    captured = capsys.readouterr()
    assert "DRY-RUN" in captured.out


def test_real_run_requires_target_id(tmp_path):
    export_root = tmp_path / "export" / "data" / "101"
    export_root.mkdir(parents=True, exist_ok=True)

    with pytest.raises(SystemExit) as excinfo:
        main(["--export-root", str(export_root)])

    assert excinfo.value.code == 2

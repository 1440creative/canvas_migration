#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
import argparse
import json

# --- Ensure repo root is on sys.path so "importers" is importable when run from scripts/ ---
THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Import after fixing sys.path
from importers.import_course import import_course, scan_export, ALL_STEPS


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    ap = argparse.ArgumentParser(description="Run course import pipeline")
    ap.add_argument("--export-root", required=True, type=Path)
    ap.add_argument("--target-course-id", required=True, type=int)
    ap.add_argument("--steps", nargs="*", default=None, help="Subset of steps to run")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    steps = args.steps or ALL_STEPS

    if args.dry_run:
        counts = scan_export(args.export_root)
        print("DRY-RUN: plan for steps")
        for s in steps:
            n = counts.get(s, 0)
            print(f" - {s}: {n} item(s)")

        # id_map summary expected by the test
        id_map_path = args.export_root / "id_map.json"
        if id_map_path.exists():
            try:
                data = json.loads(id_map_path.read_text(encoding="utf-8"))
                keys = sorted(list(data.keys())) if isinstance(data, dict) else []
                if keys:
                    print("id_map keys present:", ", ".join(keys))
                else:
                    print("id_map keys present: none")
            except Exception:
                # If unreadable/malformed, treat as none for dry-run output
                print("id_map keys present: none")
        else:
            print("id_map keys present: none")
        return 0

    # Real run (programmatic pipeline)
    res = import_course(
        target_course_id=args.target_course_id,
        export_root=args.export_root,
        canvas=None,  # wire a real Canvas client here in non-test usage if needed
        steps=steps,
        continue_on_error=True,
    )
    print("Import finished.")
    for s in steps:
        c = res.get("counts", {}).get(s, 0)
        print(f" - {s}: {c} item(s)")
    if res.get("errors"):
        print(f"Errors: {len(res['errors'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

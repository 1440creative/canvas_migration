#!/usr/bin/env python3
"""
Build a batch of static HTML course sites from a CSV definition file.

CSV format:
  Row 1:  batch_name,<name>          — names the output directory
  Row 2:  course_id,modules,title    — column headers (required, fixed order)
  Row 3+: <id>,<modules>,<title>     — one course per row

  modules: comma-separated position numbers (e.g. 1,2,3) — omit for all
  title:   display name override — omit to use the Canvas course name

Output:
  websites/<batch-name>/<course-id>/   — one self-contained site per course

Usage:
  python scripts/make_sites_batch.py --csv websites/example-batch.csv
  python scripts/make_sites_batch.py --csv websites/spring-2026.csv --dump-root export/data/target_dump
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(str(REPO_ROOT / ".env"))
    load_dotenv(str(REPO_ROOT / ".env.local"), override=True)
except ImportError:
    pass

from scripts.make_site import build_site


def _parse_modules(raw: str) -> set[int] | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return {int(n.strip()) for n in raw.split(",")}
    except ValueError:
        raise ValueError(f"Invalid modules value '{raw}' — expected comma-separated integers")


def main() -> int:
    p = argparse.ArgumentParser(description="Batch-build static HTML sites from a CSV")
    p.add_argument("--csv", type=Path, required=True,
                   help="Path to the batch CSV file")
    p.add_argument("--dump-root", type=Path,
                   default=REPO_ROOT / "export" / "data" / "target_dump",
                   help="Root of the target dump (default: export/data/target_dump)")
    p.add_argument("--websites-dir", type=Path,
                   default=REPO_ROOT / "websites",
                   help="Root output directory (default: websites/)")
    args = p.parse_args()

    csv_path = args.csv.resolve()
    if not csv_path.exists():
        p.error(f"CSV not found: {csv_path}")

    dump_root = args.dump_root.resolve()
    if not dump_root.is_dir():
        p.error(f"Dump root not found: {dump_root}")

    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        rows = [r for r in reader if any(c.strip() for c in r)]

    if not rows:
        p.error("CSV is empty")

    # Row 1: batch_name,<name>
    if rows[0][0].strip().lower() != "batch_name":
        p.error("Row 1 must be: batch_name,<name>")
    batch_name = rows[0][1].strip() if len(rows[0]) > 1 else ""
    if not batch_name:
        p.error("batch_name value is missing in row 1")

    # Row 2: headers
    if len(rows) < 2 or rows[1][0].strip().lower() != "course_id":
        p.error("Row 2 must be the header row: course_id,modules,title,exclude")

    course_rows = rows[2:]
    if not course_rows:
        p.error("No course rows found in CSV")

    out_root = args.websites_dir / batch_name
    out_root.mkdir(parents=True, exist_ok=True)

    print(f"Batch: {batch_name}")
    print(f"Courses: {len(course_rows)}")
    print(f"Output:  {out_root}\n")

    t_total = time.perf_counter()
    succeeded = []
    failed = []

    for i, row in enumerate(course_rows, 1):
        # Pad short rows
        while len(row) < 4:
            row.append("")

        course_id_raw = row[0].strip()
        modules_raw   = row[1].strip()
        title_raw     = row[2].strip()
        exclude_raw   = row[3].strip()

        if not course_id_raw:
            continue

        try:
            course_id = int(course_id_raw)
        except ValueError:
            print(f"[{i}/{len(course_rows)}] SKIP: invalid course_id '{course_id_raw}'")
            failed.append(course_id_raw)
            continue

        course_dir = dump_root / str(course_id)
        if not course_dir.is_dir():
            print(f"[{i}/{len(course_rows)}] SKIP {course_id}: directory not found")
            failed.append(str(course_id))
            continue

        try:
            module_positions = _parse_modules(modules_raw)
        except ValueError as e:
            print(f"[{i}/{len(course_rows)}] SKIP {course_id}: {e}")
            failed.append(str(course_id))
            continue

        title_override = title_raw or None
        exclude_titles = {t.strip() for t in exclude_raw.split(";") if t.strip()} or None
        out_dir = out_root / str(course_id)

        label = title_override or f"course {course_id}"
        mods_label = f" (modules {sorted(module_positions)})" if module_positions else ""
        print(f"[{i}/{len(course_rows)}] Building {label}{mods_label}...")

        try:
            build_site(course_dir, out_dir,
                       module_positions=module_positions,
                       title_override=title_override,
                       exclude_titles=exclude_titles)
            succeeded.append(str(course_id))
        except Exception as exc:
            print(f"  ERROR: {exc}", file=sys.stderr)
            failed.append(str(course_id))

    elapsed = time.perf_counter() - t_total
    print(f"\nDone in {elapsed:.1f}s")
    print(f"  Succeeded: {len(succeeded)}/{len(course_rows)}")
    if failed:
        print(f"  Failed:    {failed}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

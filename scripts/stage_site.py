#!/usr/bin/env python3
"""
Stage a Canvas course export into an editable source directory.

Processes page HTML (resolves images, copies local files, rewrites Canvas
URLs to relative paths) and writes flat, editable body-HTML files. The
staged directory becomes the source of truth for production builds via
make_site.py --source-dir, so manual edits here survive repeated builds
without ever touching the original dump.

Usage:
  python scripts/stage_site.py --course-dir export/data/target_dump/12804
  python scripts/stage_site.py --course-dir export/data/target_dump/12804 --out websites/source/12804
"""
from __future__ import annotations

import argparse
import json
import os
import re
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

import requests

from scripts.make_site import (
    _build_file_id_map,
    _process_html,
    _read_json,
)


def stage_site(course_dir: Path, out_dir: Path) -> None:
    t0 = time.perf_counter()

    meta: dict = _read_json(course_dir / "course" / "course_metadata.json") or {}
    course_name = meta.get("name") or course_dir.name

    modules_data: list = _read_json(course_dir / "modules" / "modules.json") or []
    if not modules_data:
        raise RuntimeError(f"No modules found in {course_dir}")

    file_id_map = _build_file_id_map(course_dir)

    pages_dir = course_dir / "pages"
    slug_map: dict[str, Path] = {}
    if pages_dir.exists():
        for page_dir in pages_dir.iterdir():
            if not page_dir.is_dir():
                continue
            slug = re.sub(r"^\d+_", "", page_dir.name)
            slug_map[slug] = page_dir

    session = requests.Session()
    token = os.getenv("CANVAS_TARGET_TOKEN") or os.getenv("CANVAS_SOURCE_TOKEN")
    if token:
        session.headers["Authorization"] = f"Bearer {token}"

    # Output directories
    pages_out = out_dir / "pages"
    images_out = out_dir / "images"
    files_out = out_dir / "files"
    pages_out.mkdir(parents=True, exist_ok=True)
    images_out.mkdir(parents=True, exist_ok=True)
    files_out.mkdir(parents=True, exist_ok=True)

    # Copy metadata so production builds don't need the dump at all
    (out_dir / "course_metadata.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / "modules.json").write_text(
        json.dumps(modules_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Build a full slug→file map across all modules for internal link rewriting
    all_slug_to_file: dict[str, str] = {}
    for mod in modules_data:
        for item in mod.get("items", []):
            if item.get("type") == "Page":
                slug = item.get("page_url") or ""
                if slug:
                    all_slug_to_file[slug] = f"pages/{slug}.html"

    # Process every page in the dump
    processed = skipped = 0
    for slug, page_dir in slug_map.items():
        html_path = page_dir / "index.html"
        if not html_path.exists():
            skipped += 1
            continue

        raw_html = html_path.read_text(encoding="utf-8")
        body = _process_html(
            raw_html, file_id_map, images_out, files_out, session, all_slug_to_file
        )

        (pages_out / f"{slug}.html").write_text(body, encoding="utf-8")
        processed += 1

    elapsed = time.perf_counter() - t0
    print(f"\n  Course:   {course_name}")
    print(f"  Pages:    {processed} staged ({skipped} skipped)")
    print(f"  Images:   {len(list(images_out.iterdir()))}")
    print(f"  Files:    {len(list(files_out.iterdir()))}")
    print(f"  Output:   {out_dir}")
    print(f"  Time:     {elapsed:.1f}s")
    print(f"\n  Edit pages in:  {pages_out}")
    print(f"  Production build: python scripts/make_site.py --source-dir \"{out_dir}\"")


def main() -> int:
    p = argparse.ArgumentParser(
        description="Stage a Canvas course export into an editable source directory"
    )
    p.add_argument("--course-dir", type=Path, required=True,
                   help="Path to the exported course folder")
    p.add_argument("--out", type=Path, default=None,
                   help="Output directory (default: websites/source/<course-id>)")
    args = p.parse_args()

    course_dir = args.course_dir.resolve()
    if not course_dir.is_dir():
        p.error(f"Course directory not found: {course_dir}")

    out_dir = args.out or (REPO_ROOT / "websites" / "source" / course_dir.name)
    print(f"Staging {course_dir.name} → {out_dir}...")
    stage_site(course_dir, out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

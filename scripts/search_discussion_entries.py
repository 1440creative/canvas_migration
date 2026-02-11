#!/usr/bin/env python3
"""Search discussion entries by keyword across all courses in a Canvas subaccount."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional

# --- ensure repo root on sys.path ---
THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from logging_setup import setup_logging, get_logger
from utils.api import CanvasAPI
from export.export_discussion_entries import search_and_export

DEFAULT_OUTPUT_DIR = Path("export/data/discussion_entry_search")

ENV_MAP = {
    "source": ("CANVAS_SOURCE_URL", "CANVAS_SOURCE_TOKEN"),
    "target": ("CANVAS_TARGET_URL", "CANVAS_TARGET_TOKEN"),
}


def main(argv: List[str] | None = None, *, api_override: CanvasAPI | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Search discussion entries by keyword across a Canvas subaccount.",
    )
    p.add_argument("--subaccount-id", type=int, required=True, help="Canvas subaccount id")
    p.add_argument("--keywords", required=True, help="Comma-separated keywords to match in topic titles")
    p.add_argument("--course-code", default=None, help="Filter courses by code prefix (e.g. CHRM, PRP)")
    p.add_argument(
        "--instance",
        choices=["source", "target"],
        default="source",
        help="Canvas instance to query (default: source)",
    )
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Output directory")
    p.add_argument("-v", "--verbose", action="count", default=1, help="Increase verbosity (-v, -vv)")
    args = p.parse_args(argv)

    setup_logging(verbosity=args.verbose)
    log = get_logger(artifact="discussion-entry-search", course_id=0)

    keywords = [kw.strip() for kw in args.keywords.split(",") if kw.strip()]
    if not keywords:
        log.error("No keywords provided.")
        return 2

    # Build API client
    if api_override:
        api: Optional[CanvasAPI] = api_override
    else:
        url_env, token_env = ENV_MAP[args.instance]
        base = os.getenv(url_env)
        token = os.getenv(token_env)
        if not base or not token:
            log.error("Set %s and %s in the environment.", url_env, token_env)
            return 2
        api = CanvasAPI(base, token)

    log.info(
        "searching subaccount %s for keywords: %s",
        args.subaccount_id,
        ", ".join(keywords),
    )

    results = search_and_export(api, args.subaccount_id, keywords, args.output_dir, course_code=args.course_code)

    total_entries = sum(r.get("entry_count", 0) for r in results)
    log.info(
        "done: %d matching discussion(s), %d total entries",
        len(results),
        total_entries,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

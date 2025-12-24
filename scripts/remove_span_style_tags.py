#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Remove <span> tags that include style attributes while preserving inner text.",
    )
    parser.add_argument(
        "--root",
        required=True,
        type=Path,
        help="Root directory to scan (e.g., export/data/1234/pages).",
    )
    return parser.parse_args()


def _strip_span_style(html: str) -> str:
    open_span = re.compile(r'<span\b[^>]*\bstyle="[^"]*"[^>]*>', re.I)
    close_span = re.compile(r"</span\s*>", re.I)
    return close_span.sub("", open_span.sub("", html))


def main() -> int:
    args = _parse_args()
    root: Path = args.root
    if not root.exists():
        raise SystemExit(f"root not found: {root}")

    for path in root.rglob("*.html"):
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        cleaned = _strip_span_style(text)
        if cleaned != text:
            path.write_text(cleaned, encoding="utf-8")
            print(f"updated {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

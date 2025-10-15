#!/usr/bin/env python3
"""
Batch importer for batch exports.

Given a directory of export bundles (as produced by batch_export.py),
invoke scripts/run_import.py for each bundle and optionally track results.

Usage examples:
  python scripts/batch_import_bac.py \
    --export-root export/data \
    --target-account-id 135 \
    --summary-dir docs/import_summaries \
    --record-path docs/imported_courses.txt \
    --include-quiz-questions
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence


@dataclass
class ExportBundle:
    source_id: int | None
    display_name: str
    path: Path


def iter_export_bundles(root: Path) -> Iterator[ExportBundle]:
    """Yield export bundles present under the root directory."""
    if not root.exists():
        raise FileNotFoundError(f"export root not found: {root}")

    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue

        meta_path = entry / "course" / "course_metadata.json"

        # Skip shared helper directories that are not actual course exports.
        if not entry.name.isdigit() and not meta_path.exists():
            print(f"Skipping non-course directory: {entry}")
            continue
        if not meta_path.exists():
            print(f"Skipping incomplete export (missing course metadata): {entry}")
            continue

        source_id: int | None = None
        display_name = entry.name

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}
        if isinstance(meta, dict):
            candidate = meta.get("id") or meta.get("course_id") or meta.get("canvas_course_id")
            if candidate is None and isinstance(meta.get("course"), dict):
                candidate = meta["course"].get("id")
            try:
                if candidate is not None:
                    source_id = int(str(candidate))
            except (TypeError, ValueError):
                source_id = None

            name = meta.get("name") or meta.get("course_code") or meta.get("course_code_display")
            if isinstance(name, str) and name.strip():
                display_name = name.strip()

        if source_id is None:
            try:
                source_id = int(entry.name)
            except ValueError:
                source_id = None

        yield ExportBundle(source_id=source_id, display_name=display_name, path=entry)


def build_import_command(
    export: ExportBundle,
    *,
    python_executable: str,
    target_account_id: int,
    steps: Sequence[str],
    include_quiz_questions: bool,
    resume: bool,
    summary_path: Path | None,
    extra_args: Sequence[str],
) -> list[str]:
    """Compose the command line for scripts/run_import.py."""
    cmd = [
        python_executable,
        "scripts/run_import.py",
        "--export-root",
        str(export.path),
        "--target-account-id",
        str(target_account_id),
    ]

    if steps:
        cmd += ["--steps", ",".join(steps)]

    if resume:
        cmd.append("--resume")

    if include_quiz_questions:
        cmd.append("--include-quiz-questions")
    else:
        cmd.append("--skip-quiz-questions")

    if summary_path is not None:
        cmd += ["--summary-json", str(summary_path)]

    cmd.extend(extra_args)
    return cmd


def append_record(record_path: Path, export: ExportBundle, summary_path: Path | None) -> None:
    """Append a concise record of the import to the provided file."""
    record_path.parent.mkdir(parents=True, exist_ok=True)
    summary_ref = summary_path if summary_path is None else summary_path.name
    source_ref = export.source_id if export.source_id is not None else export.path.name
    with record_path.open("a", encoding="utf-8") as fh:
        fh.write(f"{source_ref}\t{export.display_name}\t{summary_ref}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run imports for BAC courses from export bundles.")
    parser.add_argument("--export-root", type=Path, default=Path("export/data"), help="Directory containing export bundles.")
    parser.add_argument(
        "--target-account-id",
        "--target-account",
        dest="target_account_id",
        type=int,
        required=True,
        help="Target Canvas account id for new courses.",
    )
    parser.add_argument("--steps", nargs="+", default=[], help="Optional subset of import steps (same names as run_import.py).")
    parser.add_argument("--resume", action="store_true", help="Forward --resume to each run_import invocation.")
    parser.add_argument("--include-quiz-questions", action="store_true", default=True, help="Include quiz questions (default).")
    parser.add_argument("--skip-quiz-questions", action="store_false", dest="include_quiz_questions", help="Skip quiz questions.")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N bundles.")
    parser.add_argument("--offset", type=int, default=0, help="Skip the first N bundles before processing.")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing them.")
    parser.add_argument(
        "--record-path",
        type=Path,
        default=Path("docs/imported_courses.txt"),
        help="Optional TSV to append (source_id, course_name, summary filename).",
    )
    parser.add_argument(
        "--summary-dir",
        type=Path,
        default=None,
        help="If provided, write per-course summaries into this directory.",
    )
    parser.add_argument(
        "--extra-import-args",
        nargs=argparse.REMAINDER,
        default=[],
        help="Arguments appended verbatim after '--' when invoking run_import.py.",
    )
    args = parser.parse_args()

    bundles = list(iter_export_bundles(args.export_root))
    if args.offset:
        bundles = bundles[args.offset :]
    if args.limit is not None:
        bundles = bundles[: args.limit]

    if not bundles:
        print(f"No export bundles found under {args.export_root}")
        return 0

    steps: Sequence[str] = args.steps
    if args.summary_dir:
        args.summary_dir.mkdir(parents=True, exist_ok=True)

    extra_args: Sequence[str] = []
    if args.extra_import_args:
        # argparse.REMAINDER collects everything after '--', but retains the '--' element.
        # Filter out a standalone '--' to avoid confusing run_import.py.
        extra_args = [a for a in args.extra_import_args if a != "--"]

    for idx, export in enumerate(bundles, start=1):
        summary_path = None
        if args.summary_dir:
            summary_path = args.summary_dir / f"import_summary_{export.source_id or export.path.name}.json"

        cmd = build_import_command(
            export,
            python_executable=sys.executable,
            target_account_id=args.target_account_id,
            steps=steps,
            include_quiz_questions=args.include_quiz_questions,
            resume=args.resume,
            summary_path=summary_path,
            extra_args=extra_args,
        )

        print(f"\n[{idx}/{len(bundles)}] Importing {export.display_name} ({export.source_id or 'unknown id'})")
        print(" ".join(cmd))
        if args.dry_run:
            continue

        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as exc:
            print(f"Import failed for {export.display_name}: {exc}", file=sys.stderr)
            return 1

        if args.record_path:
            append_record(args.record_path, export, summary_path)

    print(f"\nCompleted imports for {len(bundles)} bundle(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

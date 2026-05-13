#!/usr/bin/env python3
"""
Dev server for staged course sites with live reload.

Watches the staged source pages directory for changes, rebuilds on save,
and signals the browser to reload automatically.

Usage:
  python scripts/serve_site.py --source-dir websites/source/12804
  python scripts/serve_site.py --source-dir websites/source/12804 --modules 1,2,3
  python scripts/serve_site.py --source-dir websites/source/12804 --port 8080
"""
from __future__ import annotations

import argparse
import http.server
import os
import sys
import threading
import time
from pathlib import Path

THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.make_site import build_site, _read_json

# Injected into nav.js after each build so the browser polls for changes
_LIVERELOAD_JS = """
(function(){
    var v=null;
    function check(){
        fetch('/__version').then(function(r){return r.text();}).then(function(next){
            if(v===null){v=next;}else if(v!==next){location.reload();}
        }).catch(function(){});
        setTimeout(check,800);
    }
    check();
})();
"""

_version = 0
_version_lock = threading.Lock()
_out_dir: Path


def _increment_version() -> None:
    global _version
    with _version_lock:
        _version += 1


def _get_version() -> str:
    with _version_lock:
        return str(_version)


class _Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/__version":
            body = _get_version().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        else:
            super().do_GET()

    def log_message(self, fmt: str, *args) -> None:
        pass  # suppress per-request noise


def _build(source_dir: Path, out_dir: Path, module_positions, exclude_titles, title, include_unpublished=False) -> None:
    try:
        build_site(
            course_dir=None,
            out_dir=out_dir,
            source_dir=source_dir,
            module_positions=module_positions,
            title_override=title,
            exclude_titles=exclude_titles,
            include_unpublished=include_unpublished,
        )
        # Append livereload snippet to nav.js
        nav = out_dir / "nav.js"
        nav.write_text(nav.read_text(encoding="utf-8") + _LIVERELOAD_JS, encoding="utf-8")
    except Exception as exc:
        print(f"  Build error: {exc}", file=sys.stderr)


def _watch(source_dir: Path, out_dir: Path, module_positions, exclude_titles, title, include_unpublished=False) -> None:
    pages_dir = source_dir / "pages"
    mtimes: dict[Path, float] = {}

    def snapshot() -> dict[Path, float]:
        return {p: p.stat().st_mtime for p in pages_dir.glob("*.html") if p.is_file()}

    mtimes = snapshot()

    while True:
        time.sleep(0.8)
        current = snapshot()
        changed = [p for p, m in current.items() if mtimes.get(p) != m]
        new_files = [p for p in current if p not in mtimes]
        if changed or new_files:
            names = ", ".join(p.name for p in (changed + new_files))
            print(f"  Changed: {names} — rebuilding...")
            _build(source_dir, out_dir, module_positions, exclude_titles, title, include_unpublished)
            _increment_version()
            print(f"  Done. Browser will reload.")
        mtimes = current


def main() -> int:
    p = argparse.ArgumentParser(description="Dev server with live reload for staged course sites")
    p.add_argument("--source-dir", type=Path, required=True,
                   help="Staged source directory (from stage_site.py)")
    p.add_argument("--out", type=Path, default=None,
                   help="Output directory for the built site (default: <source-dir>/site)")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--modules", default=None,
                   help="Comma-separated module positions to include (e.g. 1,2,3)")
    p.add_argument("--title", default=None)
    p.add_argument("--exclude", default=None,
                   help="Semicolon-separated page titles to omit")
    p.add_argument("--include-unpublished", action="store_true",
                   help="Include modules marked published=false")
    args = p.parse_args()

    source_dir = args.source_dir.resolve()
    if not source_dir.is_dir():
        p.error(f"Source directory not found: {source_dir}")

    global _out_dir
    _out_dir = args.out or (source_dir / "site")

    module_positions = None
    if args.modules:
        try:
            module_positions = {int(n.strip()) for n in args.modules.split(",")}
        except ValueError:
            p.error("--modules must be comma-separated integers")

    exclude_titles = None
    if args.exclude:
        exclude_titles = {t.strip() for t in args.exclude.split(";") if t.strip()}

    meta = _read_json(source_dir / "course_metadata.json") or {}
    course_name = args.title or meta.get("name") or source_dir.name

    print(f"Course:  {course_name}")
    print(f"Source:  {source_dir}")
    print(f"Output:  {_out_dir}")
    print(f"\nBuilding initial site...")
    _build(source_dir, _out_dir, module_positions, exclude_titles, args.title, args.include_unpublished)
    print(f"Done.\n")

    # Start watcher thread
    watcher = threading.Thread(
        target=_watch,
        args=(source_dir, _out_dir, module_positions, exclude_titles, args.title, args.include_unpublished),
        daemon=True,
    )
    watcher.start()

    # Start HTTP server — use directory parameter instead of chdir to avoid polluting cwd
    handler = lambda *a, **kw: _Handler(*a, directory=str(_out_dir), **kw)
    server = http.server.HTTPServer(("", args.port), handler)

    print(f"Serving at http://localhost:{args.port}/index.html")
    print(f"Watching: {source_dir / 'pages'}")
    print(f"Edit pages in the source dir — browser reloads on save.\n")
    print(f"Ctrl+C to stop.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

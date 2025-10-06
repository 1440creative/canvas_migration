# export/export_course.py
from __future__ import annotations

from pathlib import Path
from typing import Optional

from utils.api import CanvasAPI, source_api
from export.export_pages import export_pages
from export.export_modules import export_modules
from export.export_assignments import export_assignments
from export.export_assignment_groups import export_assignment_groups
from export.export_quizzes import export_quizzes
from export.export_discussions import export_discussions
from export.export_files import export_files
from export.export_settings import export_course_settings
from export.export_blueprint_settings import export_blueprint_settings

def export_course(course_id: int, export_root: Path, api: Optional[CanvasAPI] = None) -> None:
    """
    Export all course artifacts into export_root/{course_id}/...
    """
    api = api or source_api
    course_root = export_root / str(course_id)
    course_root.mkdir(parents=True, exist_ok=True)

    print(f"Exporting course {course_id} to {course_root}")

    export_pages(course_id, export_root, api)
    export_modules(course_id, export_root, api)
    export_assignments(course_id, export_root, api)
    export_assignment_groups(course_id, export_root, api)
    export_quizzes(course_id, export_root, api)
    export_discussions(course_id, export_root, api)
    export_files(course_id, export_root, api)
    export_course_settings(course_id, export_root, api)
    export_blueprint_settings(course_id, export_root, api)

    print(f"Export complete: {course_root}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Export a Canvas course")
    parser.add_argument("course_id", type=int, help="Canvas course ID")
    parser.add_argument("export_root", type=Path, help="Directory to save course export")
    args = parser.parse_args()
    export_course(args.course_id, args.export_root)

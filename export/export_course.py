from export.export_pages import export_pages
from export.export_modules import export_modules
from export.export_assignments import export_assignments
from export.export_discussions import export_discussions
from export.export_files import export_files
from export.export_settings import export_settings
from export.export_blueprint_settings import export_blueprint_settings

from pathlib import Path

def export_course(course_id: int, output_dir: str) -> None:
    """Export all course content and settings from Canvas
       Args:
        course_id (int): Canvas course ID
        output_dir (str): Directory to write exported content into
    """
    output_path = Path(output_dir) / str(course_id)
    output_path.mkdir(parents=True, exist_ok=True)
    
    print(f"Exporting course {course_id} to {output_path}")
    
    export_pages(course_id, output_path)
    export_modules(course_id, output_path)
    export_assignments(course_id, output_path)
    export_discussions(course_id, output_path)
    export_files(course_id, output_path)
    export_settings(course_id, output_path)
    export_blueprint_settings(course_id, output_path)
    
    print(f"Export complete: {output_path}")

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Export a Canvas course")
    parser.add_argument("course_id", type=int, help="Canvas course ID")
    parser.add_argument("output_dir", help="Directory to save course export")

    args = parser.parse_args()
    export_course(args.course_id, args.output_dir)

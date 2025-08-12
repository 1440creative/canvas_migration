# scripts/run_export_quizzes.py
from pathlib import Path
from utils.api import source_api
from export.export_quizzes import export_quizzes

if __name__ == "__main__":
    export_root = Path("export/test_data")
    course_id = 76739  # https://canvas.sfu.ca/courses/76739 (CRM110)
    export_quizzes(course_id, export_root=export_root, api=source_api, include_questions=True)

from utils.api import source_api
from utils.fs import save_json
from pathlib import Path
from typing import Dict, Any, List

def export_quizzes(course_id: int, output_dir: Path = Path("export/data")) -> None:
    endpoint = f"courses/{course_id}/quizzes"
    quizzes: List[Dict[str, Any]] = source_api.get(endpoint)

    output_path = output_dir / str(course_id) / "quizzes.json"
    save_json(quizzes, output_path)

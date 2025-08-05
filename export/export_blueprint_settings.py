# export/export_blueprint_settings.py

from pathlib import Path
from utils.api import source_api
from utils.fs import save_json

def export_blueprint_settings(course_id: int, output_dir: str = "export/data") -> None:
    """
    Export Blueprint course settings for the given course ID.

    Args:
        course_id (int): Canvas course ID
        output_dir (str): Output directory
    """
    response = source_api.get(f"/courses/{course_id}/blueprint_templates/default")
    blueprint_data = response

    base_path = Path(output_dir) / str(course_id)
    base_path.mkdir(parents=True, exist_ok=True)

    save_json(blueprint_data, base_path / "blueprint_settings.json")
# utils/fs.py

import json
from pathlib import Path
from typing import Any, Dict

def save_json(data: Dict[str, Any], filepath: Path) -> None:
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with filepath.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
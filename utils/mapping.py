#utils/mapping.py
"""
Helpers for recording old->new ID and slug mappings during import
"""

from typing import Optional

def record_mapping(
    *,
    old_id: Optional[int],
    new_id: Optional[int],
    old_slug: Optional[str],
    new_slug: Optional[str],
    id_map: dict[int, int],
    slug_map: dict[str, str],
) -> None:
    """
    Update id_map and slug_map with new Canvas IDs/URLs
    e.g.
        old_id=42,
        new_id=314
        old_slug="welcome-old",
        new_slug="woelcome",
        id_map=page_id_map,
        slug_map=page_url_map,
    """
    if old_id is not None and new_id is not None:
        id_map[old_id] = new_id
    if old_slug and new_slug:
        slug_map[str(old_slug)] = str(new_slug)
        

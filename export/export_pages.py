# import os
# import json

from utils.api import source_api
from utils.pagination import fetch_all
from utils.logging import logger
from utils.fs import save_json
from pathlib import Path

def export_pages(course_id: int, output_dir: Path = Path("export/data")) -> list[dict]:
    logger.info(f"Exporting pages for course {course_id} to {output_dir}")   
    pages = fetch_all(f"/courses/{course_id}/pages")
    metadata_list = []
    
    course_dir = output_dir / str(course_id) / "pages"
    course_dir.mkdir(parents=True, exist_ok=True)
    
    for page in pages:
        slug = page["url"]
        logger.debug(f"Fetching page '{slug}'")
        page_detail = source_api.get(f"/courses/{course_id}/pages/{slug}")
        #html_body = page_detail.get("body", "")
        
        # Save HTML
        file_path = course_dir / f"{slug}.html"
        with file_path.open("w", encoding="utf-8") as f:
            f.write(page_detail.get("body", ""))
        logger.debug(f"Saved page '{slug}' content to {file_path}")
            
        # build metadata dict
        metadata_list.append({
            "slug": slug,
            "title": page_detail.get("title"),
            "page_id": page_detail.get("page_id"),
            "published": page_detail.get("published", False),
            "html_url": page_detail.get("html_url")
        })
    #persist metadata
    metadata_path = output_dir / str(course_id) / "pages_metadata.json"
    save_json(metadata_list, metadata_path)
    logger.info(f"Exported {len(pages)} pages for course {course_id}, metadata saved to {metadata_path}")

    return metadata_list
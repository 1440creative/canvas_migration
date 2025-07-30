from utils.api import source_api
import os
import json

def export_pages(course_id, output_dir="export/data"):
    pages = source_api.get(f"/courses/{course_id}/pages")
    course_dir = os.path.join(output_dir, str(course_id), "pages")
    os.makedirs(course_dir, exist_ok=True)
    
    metadata = []
    
    for page in pages:
        slug = page["url"]
        page_detail = source_api.get(f"/course/{course_id}/pages/{slug}")
        html_body = page_detail.get("body", "")
        
        # Save HTML
        file_path = os.path.join(course_dir, f"{slug}.html")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(html_body)
            
        metadata.append({
            "title": page["title"],
            "slug": slug,
            "url": page_detail["html_url"],
            "page_id": page_detail["page_id"],
            "published": page_detail["published"]
        })
    #persist metadata
    meta_file = os.path.join(output_dir, str(course_id), "pages_metadata.json")
    with open(meta_file, "w", encoding="utf=8") as f:
        json.dump(metadata, f, indent=2)
        
    print(f"Exported {len(metadata)} pages for course {course_id}")
    return metadata
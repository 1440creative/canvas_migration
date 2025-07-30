# utils/pagination.py
import requests
from utils.api import source_api

def fetch_all(endpoint):
    """Fetch all paginated Canvas API results and return as a list."""
    results = []
    url = source_api.base_url + endpoint.lstrip("/")
    headers = {"Authorization": f"Bearer {source_api.token}"}

    while url:
        r = requests.get(url, headers=headers)
        r.raise_for_status()
        results.extend(r.json())

        # Look for next page in Link header
        link = r.headers.get("Link", "")
        next_url = None
        for part in link.split(","):
            if 'rel="next"' in part:
                next_url = part[part.find("<")+1:part.find(">")]
        url = next_url

    return results

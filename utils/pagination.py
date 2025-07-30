# utils/pagination.py
from utils.api import source_api

def fetch_all(endpoint):
    """Fetch all paginated Canvas API results using source_api's session."""
    results = []
    url = source_api.base_url + endpoint.lstrip("/")

    while url:
        r = source_api.session.get(url)  # use the session with headers
        r.raise_for_status()
        results.extend(r.json())

        # Parse Link header for rel="next"
        link = r.headers.get("Link", "")
        next_url = None
        for part in link.split(","):
            if 'rel="next"' in part:
                next_url = part[part.find("<")+1:part.find(">")]
        url = next_url

    return results

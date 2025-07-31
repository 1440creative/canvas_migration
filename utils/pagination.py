# utils/pagination.py
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from utils.api import source_api

def add_per_page(url, per_page=100):
    """Ensure per_page is set on the URL."""
    parts = list(urlparse(url))
    query = parse_qs(parts[4])
    query["per_page"] = [str(per_page)]
    parts[4] = urlencode(query, doseq=True)
    return urlunparse(parts)

def fetch_all(endpoint):
    """Fetch all paginated Canvas API results using source_api's session."""
    results = []
    url = source_api.base_url + endpoint.lstrip("/")
    url = add_per_page(url)  # force per_page=100

    while url:
        r = source_api.session.get(url)
        r.raise_for_status()
        results.extend(r.json())

        link = r.headers.get("Link", "")
        next_url = None
        for part in link.split(","):
            if 'rel="next"' in part:
                next_url = part[part.find("<")+1:part.find(">")]
        if next_url:
            next_url = add_per_page(next_url)
        url = next_url

    return results


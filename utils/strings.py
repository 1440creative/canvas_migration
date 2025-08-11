#

from __future__ import annotations
import re

# Allow alnum, dot, underscore, dash; collapse everything else to '-'
_slug_rx = re.compile(r"[^a-zA-Z0-9._-]+")

def sanitize_slug(s: str) -> str:
    """
    Filesystem-safe slug for deterministic paths.
    - spaces -> '-'
    - disallowed chars -> '-'
    - collapse multiple '-' -> single '-'
    - lowercase and trim leading/trailing '-'
    """
    s = s.strip().replace(" ", "-")
    s = _slug_rx.sub("-", s)
    s = re.sub(r"-{2,}", "-", s)
    return s.strip("-").lower()


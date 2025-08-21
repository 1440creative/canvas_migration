# utils/strings.py
from __future__ import annotations
import re
import unicodedata

_slug_sep_re = re.compile(r"[\s_]+", flags=re.UNICODE)
_non_alnum_hyphen_re = re.compile(r"[^a-z0-9\-]+", flags=re.UNICODE)
_multi_hyphen_re = re.compile(r"-{2,}")

def sanitize_slug(s: str) -> str:
    """
    Slug rules:
      - Unicode normalize + strip accents
      - Lowercase
      - Replace any run of non [a-z0-9] with "-"
      - Collapse multiple "-" and trim from ends
    """
    if not s:
        return ""
    # Normalize to ASCII
    norm = unicodedata.normalize("NFKD", s)
    ascii_s = norm.encode("ascii", "ignore").decode("ascii")

    # Lowercase
    lower = ascii_s.lower()

    # Turn *any* non-alnum run (spaces, underscores, punctuation, etc.) into "-"
    slug = re.sub(r"[^a-z0-9]+", "-", lower)

    # Collapse/trim hyphens
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug

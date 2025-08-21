#utils/dates.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

def _fromisoformat_utc_aware(ts: str) -> datetime:
    """
    Parse an ISO-8601 string into an aware datetime.

    - Accepts 'Z' suffix by translating to '+00:00'
    - Accepts offsets like '+07:00'
    - If the string is naive (no tz info), assume UTC
    """
    
    s = ts.strip()
    # normalize 'z' -> '+00:00' for fromisoformat()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
        
    dt = datetime.fromisoformat(s) # python 3.8+ offsets, fractionals
    
    if dt.tzinfo is None:
        # Canvas should include TZ; treat naive
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

def normalize_iso8601(ts: Optional[str]) -> Optional[str]:
    """
    Normalize a Canvas API timestamp string to ISO-8601 UTC (Z-notation).

    Examples
    --------
    >>> normalize_iso8601("2025-08-19T10:52:51-07:00")
    '2025-08-19T17:52:51Z'

    >>> normalize_iso8601("2025-08-19T17:52:51Z")
    '2025-08-19T17:52:51Z'

    Notes
    -----
    - Accepts None and returns None.
    - Preserves second precision (drops microseconds).
    - Always returns with trailing 'Z' (UTC).
    """
    if ts is None:
        return None
    
    dt = _fromisoformat_utc_aware(ts).astimezone(timezone.utc).replace(microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def now_utc_iso() -> str:
    """
    Return the current UTC timestamp in ISO-8601 Z notation.

    Examples
    --------
    >>> ts = now_utc_iso()
    >>> ts.endswith("Z")
    True
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


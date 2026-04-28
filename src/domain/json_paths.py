from __future__ import annotations

from typing import Any, List, Optional


def safe_get(d: Any, path: List[str], default: Optional[Any] = None) -> Any:
    """Nested dict access without raising if a segment is missing."""
    current = d
    for key in path:
        if not isinstance(current, dict):
            return default
        if key not in current:
            return default
        current = current[key]
    return current

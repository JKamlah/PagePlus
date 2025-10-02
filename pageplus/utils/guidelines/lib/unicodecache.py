"""Small helpers with LRU caches for Unicode metadata lookups."""

import unicodedataplus as unicodedata
from functools import lru_cache
from typing import Optional, Tuple


@lru_cache(maxsize=None)
def get_name(glyph: str) -> Optional[str]:
    """Return the Unicode name for *glyph* or ``None`` if undefined."""

    try:
        return unicodedata.name(glyph)
    except ValueError:
        return None


@lru_cache(maxsize=None)
def get_category(glyph: str) -> Optional[str]:
    """Return the Unicode category for *glyph* or ``None``."""

    try:
        return unicodedata.category(glyph)
    except TypeError:
        return None


def describe(glyph: str) -> Tuple[Optional[str], Optional[str], str]:
    """Return a tuple of ``(name, category, sub_category)``.

    The ``sub_category`` is derived from the first token of the Unicode name,
    matching the logic used across GTReval for grouping statistics.
    """

    name = get_name(glyph)
    category = get_category(glyph)
    if name:
        return name, category, name.split(' ')[0]
    return "Unknown", category or "Unknown", "Unknown"


"""Element filters for narrowing which regions/lines an OCR task touches.

These build the ``region_filter`` / ``line_filter`` callables consumed by
:class:`pageplus.utils.llm.pipeline.PagePlusDocumentPage`. The main use case is
the LLM-OCR tab's "Process only Tags" option, where the user supplies a set of
tags and only matching elements are sent to / updated by the model.
"""
from __future__ import annotations

import re
from typing import Callable, List, Optional, Sequence


def _element_tag(element) -> str:
    try:
        return element.get_tag() or ""
    except Exception:  # pragma: no cover - defensive
        return ""


def make_tag_filter(
    tags: Optional[Sequence[str]],
    *,
    regex: bool = False,
) -> Optional[Callable[[object], bool]]:
    """Return a predicate matching elements whose tag is in ``tags``.

    - ``tags`` empty/None -> returns ``None`` (no filtering).
    - ``regex=False`` (default): case-insensitive exact match against any tag.
    - ``regex=True``: each entry is treated as a regular expression and matched
      with :func:`re.search` (case-insensitive), mirroring the Kraken/Tesseract
      ``*_tagfilter`` behaviour.
    """
    cleaned: List[str] = [t.strip() for t in (tags or []) if t and t.strip()]
    if not cleaned:
        return None

    if regex:
        patterns = [re.compile(t, re.IGNORECASE) for t in cleaned]

        def _regex_predicate(element) -> bool:
            tag = _element_tag(element)
            return any(p.search(tag) for p in patterns)

        return _regex_predicate

    lowered = {t.lower() for t in cleaned}

    def _exact_predicate(element) -> bool:
        return _element_tag(element).lower() in lowered

    return _exact_predicate


def get_table_row_count(region: object) -> int:
    """Extract the row count of a TableRegion element or model instance."""
    rows = set()
    max_row_idx = 0

    cells = getattr(region, "tablecells", None)
    if cells:
        for c in cells:
            elem = getattr(c, "xml_element", None)
            if elem is not None and elem.get("row") is not None:
                try:
                    r = int(elem.get("row"))
                    rs = int(elem.get("rowSpan", 1))
                    max_row_idx = max(max_row_idx, r + rs)
                    rows.add(r)
                except (TypeError, ValueError):
                    pass

    elem = getattr(region, "xml_element", region)
    if elem is not None and hasattr(elem, "iter"):
        for tc in elem.iter():
            if str(getattr(tc, "tag", "")).endswith("TableCell") and tc.get("row") is not None:
                try:
                    r = int(tc.get("row"))
                    rs = int(tc.get("rowSpan", 1))
                    max_row_idx = max(max_row_idx, r + rs)
                    rows.add(r)
                except (TypeError, ValueError):
                    pass

    return max(len(rows), max_row_idx)


def make_table_row_filter(
    min_rows: Optional[int] = None,
    max_rows: Optional[int] = None,
) -> Optional[Callable[[object], bool]]:
    """Return a predicate matching TableRegion elements whose row count falls
    within [min_rows, max_rows].

    - If both ``min_rows`` and ``max_rows`` are None -> returns ``None`` (no filter).
    - Non-table elements automatically pass through.
    """
    if min_rows is None and max_rows is None:
        return None

    def _row_predicate(element) -> bool:
        tag_or_type = str(getattr(element, "tag", getattr(element, "type", "")))
        elem_name = type(element).__name__.lower()
        is_table = "table" in tag_or_type.lower() or "table" in elem_name or hasattr(element, "tablecells")
        if not is_table:
            return True

        rows = get_table_row_count(element)
        if min_rows is not None and rows < min_rows:
            return False
        if max_rows is not None and rows > max_rows:
            return False
        return True

    return _row_predicate


def combine_region_filters(
    *filters: Optional[Callable[[object], bool]]
) -> Optional[Callable[[object], bool]]:
    """Combine multiple region predicates using logical AND."""
    active = [f for f in filters if f is not None]
    if not active:
        return None
    if len(active) == 1:
        return active[0]

    def _combined(element) -> bool:
        return all(f(element) for f in active)

    return _combined

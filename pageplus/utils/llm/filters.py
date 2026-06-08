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

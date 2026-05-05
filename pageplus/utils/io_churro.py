"""Churro document format <-> PAGE-XML conversion utilities.

These helpers convert between PagePlus's PAGE-XML representation and the JSON
serialization of Churro's ``DocumentOCRResult`` / ``DocumentPage`` objects
(see ``churro_ocr.document.DocumentOCRResult`` and
``churro_ocr.page_detection.DocumentPage`` upstream).

PagePlus does **not** depend on the ``churro-ocr`` Python package at runtime;
we only read and write the JSON layout that Churro's ``.model_dump()`` /
``.to_dict()`` helpers produce. This lets users drop a ``.churro.json`` file
into PagePlus and get a browsable PAGE-XML page for it, and likewise export a
PAGE-XML corpus into Churro JSON for benchmarking or downstream Churro tools.

Supported Churro JSON shapes
----------------------------
**Per-page (single DocumentPage)**::

    {
      "page_index": 0,
      "source_index": 0,
      "bbox": [x0, y0, x1, y1],        # optional
      "polygon": [[x, y], ...],        # optional
      "metadata": { ... },
      "text": "...",                    # OCR output, \\n-delimited lines
      "provider_name": "hf",
      "model_name": "stanford-oval/churro-3B",
      "ocr_metadata": { ... }
    }

**Document-level (DocumentOCRResult)**::

    {
      "source_type": "image" | "pdf",
      "metadata": { ... },
      "pages": [ <DocumentPage>, ... ]
    }

We also accept a bare list of ``DocumentPage`` objects and a dict with a
``pages`` key as loose synonyms for the document-level shape.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from PIL import Image

from pageplus.models.page import Page

logger = logging.getLogger(__name__)

PAGE_NS_2013 = "http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15"
PAGE_XSI_LOCATION = (
    f"{PAGE_NS_2013} "
    "http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15/pagecontent.xsd"
)


# ---------------------------------------------------------------------------
# Dataclass mirror of Churro's DocumentPage / DocumentOCRResult
# ---------------------------------------------------------------------------


BBox = Tuple[float, float, float, float]
Polygon = Sequence[Tuple[float, float]]


@dataclass
class ChurroDocumentPage:
    """Lossless mirror of ``churro_ocr.page_detection.DocumentPage`` as JSON."""

    page_index: int = 0
    source_index: int = 0
    bbox: Optional[BBox] = None
    polygon: Optional[List[Tuple[float, float]]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    text: Optional[str] = None
    provider_name: Optional[str] = None
    model_name: Optional[str] = None
    ocr_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return _drop_none(asdict(self))

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChurroDocumentPage":
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict for ChurroDocumentPage, got {type(data).__name__}")
        bbox = data.get("bbox")
        polygon = data.get("polygon")
        return cls(
            page_index=int(data.get("page_index", 0)),
            source_index=int(data.get("source_index", 0)),
            bbox=tuple(bbox) if bbox else None,
            polygon=[tuple(p) for p in polygon] if polygon else None,
            metadata=dict(data.get("metadata") or {}),
            text=data.get("text"),
            provider_name=data.get("provider_name"),
            model_name=data.get("model_name"),
            ocr_metadata=dict(data.get("ocr_metadata") or {}),
        )


@dataclass
class ChurroDocument:
    """Lossless mirror of ``churro_ocr.document.DocumentOCRResult`` as JSON."""

    pages: List[ChurroDocumentPage] = field(default_factory=list)
    source_type: str = "image"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_type": self.source_type,
            "metadata": dict(self.metadata),
            "pages": [p.to_dict() for p in self.pages],
        }

    @classmethod
    def from_dict(cls, data: Any) -> "ChurroDocument":
        pages_raw, source_type, metadata = _extract_document_shape(data)
        return cls(
            pages=[ChurroDocumentPage.from_dict(p) for p in pages_raw],
            source_type=source_type,
            metadata=dict(metadata or {}),
        )


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_churro_json(path: Union[str, Path]) -> ChurroDocument:
    """Load a Churro JSON file in any of the accepted shapes."""
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return ChurroDocument.from_dict(data)


def _extract_document_shape(data: Any) -> Tuple[List[Dict[str, Any]], str, Dict[str, Any]]:
    """Normalise any of the accepted Churro JSON shapes to (pages, source_type, metadata)."""
    if isinstance(data, list):
        # Bare list of DocumentPage
        return list(data), "image", {}

    if not isinstance(data, dict):
        raise ValueError(
            f"Unsupported Churro JSON root type: {type(data).__name__}. "
            "Expected dict (DocumentOCRResult or DocumentPage) or list of DocumentPage."
        )

    # Document-level result
    if "pages" in data and isinstance(data["pages"], list):
        return (
            list(data["pages"]),
            str(data.get("source_type", "image")),
            dict(data.get("metadata") or {}),
        )

    # Single page DocumentPage
    if "text" in data or "page_index" in data:
        return [data], "image", {}

    raise ValueError(
        "Unrecognised Churro JSON structure. Expected keys 'pages' (document) "
        "or 'text'/'page_index' (single page)."
    )


# ---------------------------------------------------------------------------
# Churro -> PAGE-XML
# ---------------------------------------------------------------------------


def churro_page_to_page_xml(
    page: ChurroDocumentPage,
    *,
    image_path: Optional[Path] = None,
    image_size: Optional[Tuple[int, int]] = None,
    region_id: str = "r1",
    text_delimiter: str = "\n",
) -> str:
    """Convert a single Churro ``DocumentPage`` JSON object to a PAGE-XML string.

    Churro ``DocumentPage`` carries only page-level OCR text (newline-delimited
    lines) plus an optional bbox/polygon for the page crop. We therefore emit
    a PAGE-XML with a single ``TextRegion`` spanning the page, containing one
    ``TextLine`` per newline-separated line. Per-line coordinates are
    approximated by evenly splitting the page height -- this is a pragmatic
    default that preserves reading order while making clear that exact line
    geometry was not provided by the source.
    """
    width, height = _resolve_image_size(image_path, image_size, page)
    image_filename = image_path.name if image_path is not None else _image_hint_from_metadata(page)

    region_coords = _polygon_to_points(page.polygon) or _bbox_to_polygon_points(
        page.bbox, width, height
    )

    lines = _split_text_lines(page.text or "", text_delimiter)
    line_coords = _approximate_line_coords(len(lines), width, height, page.bbox, page.polygon)

    now_iso = datetime.now().isoformat()
    xml_lines: List[str] = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        f'<PcGts xmlns="{PAGE_NS_2013}" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        f'xsi:schemaLocation="{PAGE_XSI_LOCATION}">',
        "    <Metadata>",
        "        <Creator>PagePlus (churro-format ingest)</Creator>",
        f"        <Created>{now_iso}</Created>",
        f"        <Comments>Imported from Churro DocumentPage "
        f'(provider="{page.provider_name or ""}", model="{page.model_name or ""}")</Comments>',
        "    </Metadata>",
        f'    <Page imageFilename="{image_filename}" imageWidth="{width}" imageHeight="{height}">',
        f'        <TextRegion id="{region_id}" custom="structure {{type:paragraph;}}">',
        f'            <Coords points="{region_coords}"/>',
    ]

    for i, (line_text, coords) in enumerate(zip(lines, line_coords), start=1):
        line_id = f"{region_id}_l{i}"
        baseline = _baseline_from_line_coords(coords)
        xml_lines.append(
            f'            <TextLine id="{line_id}" custom="readingOrder {{index:{i-1};}}">'
        )
        xml_lines.append(f'                <Coords points="{coords}"/>')
        xml_lines.append(f'                <Baseline points="{baseline}"/>')
        xml_lines.append("                <TextEquiv>")
        xml_lines.append(f"                    <Unicode>{escape(line_text)}</Unicode>")
        xml_lines.append("                </TextEquiv>")
        xml_lines.append("            </TextLine>")

    xml_lines.append("        </TextRegion>")
    xml_lines.append("    </Page>")
    xml_lines.append("</PcGts>")
    return "\n".join(xml_lines)


def churro_document_to_page_xmls(
    document: ChurroDocument,
    *,
    image_lookup: Optional["ChurroImageLookup"] = None,
    text_delimiter: str = "\n",
) -> List[Tuple[ChurroDocumentPage, str]]:
    """Convert every page of a Churro document to a PAGE-XML string.

    The optional ``image_lookup`` maps each ``DocumentPage`` to an image path
    on disk (used to recover real width/height and the PAGE ``imageFilename``).
    """
    results: List[Tuple[ChurroDocumentPage, str]] = []
    for page in document.pages:
        image_path = image_lookup(page) if image_lookup else None
        xml = churro_page_to_page_xml(
            page,
            image_path=image_path,
            text_delimiter=text_delimiter,
        )
        results.append((page, xml))
    return results


ChurroImageLookup = Any  # Callable[[ChurroDocumentPage], Optional[Path]]


# ---------------------------------------------------------------------------
# PAGE-XML -> Churro
# ---------------------------------------------------------------------------


def page_xml_to_churro_page(
    xml_path: Union[str, Path],
    *,
    page_index: int = 0,
    source_index: int = 0,
    provider_name: Optional[str] = None,
    model_name: Optional[str] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
    reading_order: bool = True,
    dehyphenate: bool = False,
    text_delimiter: str = "\n",
) -> ChurroDocumentPage:
    """Convert a PagePlus PAGE-XML file to a single Churro ``DocumentPage``.

    We use ``Page.extract_fulltext`` so reading order / dehyphenation follow
    the existing PagePlus conventions.
    """
    xml_path = Path(xml_path)
    page = Page(xml_path)
    text = page.extract_fulltext(
        reading_order=reading_order,
        dehyphenate=dehyphenate,
        delimiter=text_delimiter,
    )

    width, height = page.page_size()
    metadata = {
        "source_file": str(xml_path),
        "image_filename": page.imageFilename() or "",
        "image_width": int(width) if width else None,
        "image_height": int(height) if height else None,
    }
    if extra_metadata:
        metadata.update(extra_metadata)

    return ChurroDocumentPage(
        page_index=page_index,
        source_index=source_index,
        bbox=(0.0, 0.0, float(width or 0), float(height or 0)) if width and height else None,
        polygon=None,
        metadata=_drop_none(metadata),
        text=text,
        provider_name=provider_name,
        model_name=model_name,
        ocr_metadata={},
    )


def page_xmls_to_churro_document(
    xml_paths: Iterable[Union[str, Path]],
    *,
    source_type: str = "image",
    provider_name: Optional[str] = None,
    model_name: Optional[str] = None,
    reading_order: bool = True,
    dehyphenate: bool = False,
    text_delimiter: str = "\n",
    document_metadata: Optional[Dict[str, Any]] = None,
) -> ChurroDocument:
    """Bundle multiple PAGE-XML files into a Churro ``DocumentOCRResult`` JSON shape."""
    pages: List[ChurroDocumentPage] = []
    for idx, xml in enumerate(xml_paths):
        pages.append(
            page_xml_to_churro_page(
                xml,
                page_index=idx,
                source_index=idx,
                provider_name=provider_name,
                model_name=model_name,
                reading_order=reading_order,
                dehyphenate=dehyphenate,
                text_delimiter=text_delimiter,
            )
        )
    return ChurroDocument(
        pages=pages,
        source_type=source_type,
        metadata=dict(document_metadata or {}),
    )


def write_churro_document(document: ChurroDocument, path: Union[str, Path]) -> Path:
    """Write a :class:`ChurroDocument` to disk as pretty-printed JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(document.to_dict(), f, ensure_ascii=False, indent=2)
    return path


def write_churro_page(page: ChurroDocumentPage, path: Union[str, Path]) -> Path:
    """Write a single ``DocumentPage`` JSON to disk."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(page.to_dict(), f, ensure_ascii=False, indent=2)
    return path


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _drop_none(data: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in data.items() if v is not None}


def _split_text_lines(text: str, delimiter: str) -> List[str]:
    if not text:
        return []
    lines = [ln for ln in text.split(delimiter) if ln.strip()]
    return lines or [text]


def _resolve_image_size(
    image_path: Optional[Path],
    image_size: Optional[Tuple[int, int]],
    page: ChurroDocumentPage,
) -> Tuple[int, int]:
    if image_size is not None:
        return int(image_size[0]), int(image_size[1])
    if image_path is not None and image_path.exists():
        try:
            with Image.open(image_path) as img:
                return img.size
        except Exception as exc:
            logger.warning("Failed to read image size from %s: %s", image_path, exc)
    # Fall back to metadata hints
    meta = page.metadata or {}
    width = meta.get("image_width") or meta.get("width")
    height = meta.get("image_height") or meta.get("height")
    if width and height:
        return int(width), int(height)
    # Last resort: derive from bbox
    if page.bbox:
        x0, y0, x1, y1 = page.bbox
        return max(int(x1 - x0), 1), max(int(y1 - y0), 1)
    return 1000, 1000


def _image_hint_from_metadata(page: ChurroDocumentPage) -> str:
    meta = page.metadata or {}
    for key in ("image_filename", "image_path", "source_path", "path"):
        value = meta.get(key)
        if value:
            return Path(str(value)).name
    return f"page_{page.page_index:04d}.png"


def _polygon_to_points(polygon: Optional[Sequence[Tuple[float, float]]]) -> str:
    if not polygon:
        return ""
    return " ".join(f"{int(round(x))},{int(round(y))}" for x, y in polygon)


def _bbox_to_polygon_points(
    bbox: Optional[BBox], width: int, height: int
) -> str:
    if bbox is None:
        x0, y0, x1, y1 = 0, 0, width, height
    else:
        x0, y0, x1, y1 = (int(round(v)) for v in bbox)
    return f"{x0},{y0} {x1},{y0} {x1},{y1} {x0},{y1}"


def _approximate_line_coords(
    n_lines: int,
    width: int,
    height: int,
    bbox: Optional[BBox],
    polygon: Optional[Sequence[Tuple[float, float]]],
) -> List[str]:
    """Evenly tile the page region vertically so each line gets a placeholder box.

    This is an approximation; PAGE consumers that care about exact coordinates
    should re-run layout detection. The coordinates still preserve reading
    order and give visual tools something to draw.
    """
    if n_lines == 0:
        return []

    if polygon:
        xs = [p[0] for p in polygon]
        ys = [p[1] for p in polygon]
        x0, y0, x1, y1 = int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))
    elif bbox:
        x0, y0, x1, y1 = (int(round(v)) for v in bbox)
    else:
        x0, y0, x1, y1 = 0, 0, width, height

    region_height = max(y1 - y0, n_lines)
    step = region_height / n_lines
    coords: List[str] = []
    for i in range(n_lines):
        top = int(round(y0 + i * step))
        bottom = int(round(y0 + (i + 1) * step))
        if bottom <= top:
            bottom = top + 1
        coords.append(f"{x0},{top} {x1},{top} {x1},{bottom} {x0},{bottom}")
    return coords


def _baseline_from_line_coords(coords: str) -> str:
    """Derive a baseline as the mid-height horizontal of the line box."""
    try:
        pts = [tuple(int(v) for v in pt.split(",")) for pt in coords.split()]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        y_mid = int(round((min(ys) + max(ys)) / 2))
        return f"{min(xs)},{y_mid} {max(xs)},{y_mid}"
    except Exception:
        return coords

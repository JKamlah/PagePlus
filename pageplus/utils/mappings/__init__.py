"""LLM-output → PAGE XML mapping converters.

Each sub-module handles one specific JSON/text format. Import the public
functions directly from this package::

    from pageplus.utils.mappings import gemini2d_to_page, table_json_to_page
"""

from pageplus.utils.mappings.mapping_utils import (
    load_gemini2d_json,
    page_xml_header,
    page_xml_footer,
    PP_LAYOUT_LABEL_TO_TAG,
    PP_LAYOUT_LABEL_TO_STRUCTURE,
)
from pageplus.utils.mappings.gemini2d import gemini2d_to_page, gemini2d_preprocess
from pageplus.utils.mappings.table_json import table_json_to_page
from pageplus.utils.mappings.markdown import markdown2pagexml
from pageplus.utils.mappings.pp_layout import pp_layout_json_to_page
from pageplus.utils.mappings.pp_layout_extend import pp_layout_extend_json_to_page
from pageplus.utils.mappings.pp_layout_extend_table import pp_layout_extend_table_json_to_page
from pageplus.utils.mappings.segmentation import segmentation_to_page

__all__ = [
    "load_gemini2d_json",
    "page_xml_header",
    "page_xml_footer",
    "PP_LAYOUT_LABEL_TO_TAG",
    "PP_LAYOUT_LABEL_TO_STRUCTURE",
    "gemini2d_to_page",
    "gemini2d_preprocess",
    "table_json_to_page",
    "markdown2pagexml",
    "pp_layout_json_to_page",
    "pp_layout_extend_json_to_page",
    "pp_layout_extend_table_json_to_page",
    "segmentation_to_page",
]

from pathlib import Path
from typing import Tuple

import lxml.etree as ET


def parse_xml(filepath: Path = '') -> Tuple[ET.Element, ET._ElementTree, str]:
    """
    Parses an XML file and returns its root element, the ElementTree object, and the XML namespace.

    Parameters:
    filepath (Path): The path to the XML file.

    Returns:
    Tuple[ET.Element, ET.ElementTree, str]: A tuple containing the root element, the ElementTree object,
    and the XML namespace.
    """
    tree = ET.parse(str(filepath.absolute()))
    root = tree.getroot()
    # Extracting namespace from the root tag
    namespace = tree.xpath('namespace-uri(.)')
    return tree, root, namespace

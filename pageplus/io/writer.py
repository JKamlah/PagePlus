from pathlib import Path


def write_xml(page, filepath: Path) -> None:
    """
    Writes an XML page to a file.

    Parameters:
    page (Page): The Page object containing the XML ElementTree to be written.
    filepath (Path): The file path where the XML data will be saved.
    """
    filepath.parent.mkdir(parents=True, exist_ok=True)
    page.tree.write(str(filepath.absolute()),
                    xml_declaration=True,
                    standalone=True,
                    encoding='utf-8')

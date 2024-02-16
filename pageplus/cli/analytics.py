from pathlib import Path
from typing import List

import typer
from rich.progress import track
from typing_extensions import Annotated

from pageplus.analytics.counter import PageCounter
from pageplus.io.logger import logging
from pageplus.io.utils import collect_xml_files
from pageplus.models.page import Page

app = typer.Typer()


@app.command()
def statistics(
        inputs: Annotated[List[str],
        typer.Argument(exists=True, help="Paths to the XML files to be checked.")]
):
    """
    Statistics about PAGE XML files.

    This function processes each specified XML file, collects statistics about
    text regions, text lines, and table regions within those regions.

    Args:
        inputs: An iterator of Path objects pointing to the XML files to be checked.

    Raises:
        FileNotFoundError: If no XML files are found in the given input paths.
    """
    xml_files = collect_xml_files(map(Path, inputs))
    # Raise error if no xml files are found
    if not xml_files:
        raise FileNotFoundError('No xml files found in input directory')

    # Create statistics for all pages
    pagescounter = PageCounter()

    # Loop through all XML files
    for xml_file in track(xml_files, description="Collecting statistics.."):
        filename = xml_file.name
        logging.info('Processing file: ' + filename)
        # Initialize Page object and PageCounter for the current file
        page = Page(xml_file)
        page_counter = PageCounter()

        # Collect statistics for the current page
        page_counter.textregions += page.counter(level='textregions')
        page_counter.tableregions += page.counter(level='tableregions')
        page_counter.textlines += page.counter(level='textlines')
        page_counter.words += page.counter(level='words')
        page_counter.glyphs += page.counter(level='glyphs')

        # Log statistics for the current page
        page_counter.statistics(pre_text=f"Statistics for {filename}")

        # Aggregate statistics for all pages
        pagescounter += page_counter

    # Log cumulative statistics
    pagescounter.statistics(pre_text=f"Statistics for all {len(xml_files)} PAGE-XML")


if __name__ == "__main__":
    app()

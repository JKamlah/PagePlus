from pathlib import Path
from typing import List

import typer
from rich.progress import track
from typing_extensions import Annotated

from pageplus.io.logger import logging
from pageplus.utils.fs import collect_xml_files
from pageplus.models.page import Page
from pageplus.utils.fs import transform_inputs

app = typer.Typer()


@app.command()
def validate_all(
        inputs: Annotated[List[str], typer.Argument(exists=True,
                                                    help="Paths or workspace to the files to be validated.",
                                                    callback=transform_inputs)] = None):
    """
    Validates PAGE XML files.

    This function processes each specified XML file, performing a series of validation checks on
    text regions, text lines, and baselines within those regions. It logs the status of validation
    and any errors encountered during the process.

    Args:
        inputs: An iterator of Path objects pointing to the XML files to be validated.

    Raises:
        FileNotFoundError: If no XML files are found in the given input paths.
    """
    xml_files = collect_xml_files(map(Path, inputs))

    if not xml_files:
        raise FileNotFoundError('No xml files found in input directory')

    def validate_region(region):
        """
        Validates a specific region and its text lines.

        This function checks each text line within a region for compliance with expected
        standards, such as correct text, region, and baseline validation.

        Args:
            region: The region (either text or table cell) to validate.
        """
        for line in region.textlines:
            try:
                line.validate_text()
                line.validate_region()
                line.validate_baseline()
            except Exception as e:
                logging.error(f"{line.get_id()}: Error during validation - {e}")

        if region.counter(level='textlines') == 0:
            logging.info(f"{region.get_id()}: Region contains no text.")

    for xml_file in track(sorted(xml_files), description="Validating files..."):
        filename = xml_file.name
        logging.info('Validating file: ' + filename)

        page = Page(xml_file)

        # Validate text regions
        for textregion in page.regions.textregions:
            validate_region(textregion)

        # Validate table regions
        for tableregion in page.regions.tableregions:
            for tablecell in tableregion.tablecells:
                validate_region(tablecell)


if __name__ == "__main__":
    app()
